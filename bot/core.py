from __future__ import annotations

import traceback
import asyncio
import chat_rag
import token_usage
import roulette.roulette
from roulette import database as roulette_db

from typing import cast
from helper_fun import read_id
from output import (BotIdentity, group_poke, recall, send_group_original, send_msg,
                    set_msg_emoji_like)
from bot.options import AdminAPI, OptionsStore, RosterStore
from bot.plugin import Deps, AfterHook, EventHandler, Feature, Plugin, registered
from bot.request import (EmojiLike, Forward, Outbound, Outcome, Poke, Recall, Reply,
                         Request)
from bot import plugins as _plugins  # noqa: F401  触发插件注册
from constant import *


class BotCore:
    """组合根 + 调度核心。

    职责只剩三件：装配（造 Deps、构造插件）、派发（功能链 / 事件链）、
    收尾（记语料、发消息）。配置存储搬去了 bot.options，插件基类搬去了 bot.plugin。
    """

    def __init__(self):
        self.super_admin: int = SUPERADMIN
        self.own_id: int = 0
        self.own_nickname: str = ''
        # 合并转发节点的署名。值从 NapCat 现取（init_async），不是硬编码常量。
        self.identity: BotIdentity | None = None
        self.store = OptionsStore(DocPath.OPTIONS, JsonPath.GROUP_OPTIONS)
        self.roster = RosterStore(JsonPath.ADMINISTRATORS, JsonPath.BLACKLIST)
        # 全部插件按名字索引 —— AdminAPI 与 Deps 共享同一个可变 dict，
        # 插件构造完在原地填充，于是插件之间能互相拿到而不必在构造期成环。
        self._plugin_map: dict[str, Plugin] = {}
        self.api = AdminAPI(store=self.store, roster=self.roster, plugins=self._plugin_map)
        self.deps: Deps | None = None
        self.plugins: list[Plugin] = []
        self.features: list[Feature] = []
        self.event_handlers: list[EventHandler] = []
        self.after_hooks: list[AfterHook] = []

    async def init_async(self):
        chat_rag.init_db()
        await chat_rag.init_embeddings()
        token_usage.init_db()
        # roulette 的建表函数一直没人调用 —— 库文件已存在时看不出来，一旦全新部署
        # 就会「开始轮盘」报 no such table: match
        roulette_db.init_db()
        self.own_id, self.own_nickname = await read_id()
        self.identity = BotIdentity(uin=self.own_id, name=self.own_nickname)

        self.deps = Deps(
            own_id=self.own_id,
            own_nickname=self.own_nickname,
            api=self.api,
            plugins=self._plugin_map,
        )
        self.plugins = self._construct_plugins()
        self.features = cast(list[Feature],
                             [p for p in self.plugins if p.plugin_type == PluginName.FEATURE])
        self.event_handlers = cast(list[EventHandler],
                                   [p for p in self.plugins
                                    if p.plugin_type == PluginName.EVENT_HANDLER])
        self.after_hooks = cast(list[AfterHook],
                                [p for p in self.plugins
                                 if p.plugin_type == PluginName.AFTER_HOOK])
        self._plugin_map.update({p.name: p for p in self.plugins})

        # 注册表里有、options.txt 里没有的功能补成 =0（原先必须手动补，漏了静默默认关闭）
        added = self.store.ensure_keys([str(p.name) for p in self.plugins])
        if added:
            print(f"!!! options.txt 缺少 {len(added)} 个功能开关，已补为 0：{'、'.join(added)}")

    def _construct_plugins(self) -> list[Plugin]:
        """唯一的构造协议：`cls(deps)`。

        原先这里有三个按类硬编码的分支（FeatureAdmin 要 api、FeatureRoulette 要
        身份、FeatureChatRAG 要昵称），加一个带依赖的功能就得改这里。
        """
        classes = [c for c in registered() if not c.abstract and c.name]
        self._validate_registry(classes)
        plugins = [cls(self.deps) for cls in classes]
        plugins.sort(key=lambda p: p.priority)
        return plugins

    @staticmethod
    def _validate_registry(classes: list[type[Plugin]]) -> None:
        """启动校验：重名、重复优先级、以及「有类无清单 / 有清单无类」。

        优先级重复尤其要拦：现在 22 个恰好唯一，但没有任何东西保证唯一，
        一旦撞号 sort 会退化成不确定顺序，而且不会报错。
        """
        if not classes:
            raise RuntimeError(
                "一个插件都没注册 —— 显式注册的代价就在这里：漏掉一个 import，"
                "插件不会注册、也不会自己报错，整个机器人会静默地什么功能都没有。"
                "检查 bot/plugins/__init__.py 的导入链。")

        seen: dict[str, type[Plugin]] = {}
        for cls in classes:
            if cls.name in seen:
                raise RuntimeError(f"插件重名：{cls.name}（{seen[cls.name].__name__} / {cls.__name__}）")
            seen[cls.name] = cls

        for kind in (PluginName.FEATURE, PluginName.EVENT_HANDLER, PluginName.AFTER_HOOK):
            group = [c for c in classes if c.plugin_type == kind]
            prios: dict[int, str] = {}
            for cls in group:
                if cls.priority in prios:
                    raise RuntimeError(
                        f"插件优先级重复：{cls.priority}（{prios[cls.priority]} / {cls.__name__}）")
                prios[cls.priority] = cls.__name__

        unknown = [c.__name__ for c in classes if c.name not in FEATURE_ALIAS]
        if unknown:
            raise RuntimeError(f"这些插件没有登记到 FEATURE_ALIAS：{unknown}")

        have = {str(c.name) for c in classes}
        missing = [str(n) for n in FEATURE_MANIFEST if str(n) not in have]
        if missing:
            raise RuntimeError(
                f"FEATURE_MANIFEST 里这些功能没有插件类（有清单无类）：{missing}")

    # ── 消息处理 ────────────────────────────────────────────────────────────

    def _build_request(self, event) -> Request:
        """把 NapCat 事件转成 Request。这是唯一的构造点。"""
        group_id = event.get('group_id', 0)
        is_group = event["message_type"] == Name.GROUP
        return Request(
            qq=event['sender']['user_id'],
            group_id=group_id,
            msg=event['raw_message'].replace('\r\n', '\n'),
            msg_type=event["message_type"],
            nickname=event['sender']['nickname'],
            message_id=event.get('message_id', 0),
            own_id=self.own_id,
            own_nickname=self.own_nickname,
            options=(self.store.effective(group_id) if is_group
                     else dict(self.store.global_options)),
            admin=tuple(self.roster.admins),
            blacklist=tuple(self.roster.blacklist),
            super_admin=self.super_admin,
        )

    async def _run_chain(self, req: Request) -> Outcome:
        """功能链：按 priority 线性扫描，首次 consume 即停。"""
        for feature in self.features:
            if not feature.is_enabled(req.options):
                continue
            try:
                out = await feature.function(req)
            except Exception as e:      # noqa: BLE001
                print(f"!!! Feature {feature.name} 异常 !!!\n{traceback.format_exc()}")
                # 出错文案回到**这条消息来的会话** —— 原先硬编码 group_id，
                # 私聊出错会发到 number=0
                return Outcome.handled(Reply.same_conversation(
                    req, f"处理「{req.msg}」时出错：{str(e)[:100]}"))
            if out.consumed:
                return out
        return Outcome.pass_()

    async def _handle_message(self, event) -> None:
        req = self._build_request(event)

        # 空消息（NapCat 渲染不出的红包等元素会给出空 raw_message）没有任何信息，
        # 静默消费掉：既不让功能链看到它（FeatureAdmin 会下标越界），也不让它进语料库。
        if (req.qq == self.own_id or req.qq in req.blacklist
                or DELIMITER in req.msg or not req.msg.strip()):
            outcome = Outcome.silent()
        else:
            outcome = await self._run_chain(req)

        await self._run_after_hooks(req, outcome)

        await self._emit(outcome)

    async def _emit(self, outcome: Outcome) -> None:
        """把一条结论里的东西都发出去。功能链与事件链共用这一处。"""
        for action in outcome.actions:
            try:
                await self._dispatch(action)
            except Exception:           # noqa: BLE001
                print(f"!!! 发送消息失败 !!!\n{traceback.format_exc()}")

    async def _dispatch(self, out: Outbound) -> None:
        """把一条 outbound 交给 output。**全项目唯一调用 output 的地方。**

        功能与事件处理器都只返回数据，不许自己发 —— 否则「什么时候发、发几条、
        发失败怎么办」就散落到各处，`Outcome.silent()` 也会变成谎话（明明发了
        却说没发），而发送节奏更是没法统管。
        """
        if isinstance(out, Reply):
            if out.gap:
                await asyncio.sleep(out.gap)
            await send_msg(out.as_dict(), self.identity)
        elif isinstance(out, Forward):
            if out.gap:
                await asyncio.sleep(out.gap)
            await send_group_original(list(out.nodes), out.number)
        elif isinstance(out, EmojiLike):
            await set_msg_emoji_like(out.message_id, out.emoji_id)
        elif isinstance(out, Poke):
            await group_poke(out.qq, out.group_id)
        elif isinstance(out, Recall):
            await recall(out.group_id, out.message_id, out.qq)

    async def _run_after_hooks(self, req: Request, outcome: Outcome) -> None:
        """功能链之后的观察者。跑在发消息之前 —— 记语料用的是原始消息。"""
        for hook in self.after_hooks:
            if not hook.is_enabled(req.options):
                continue
            try:
                await hook.after(req, outcome)
            except Exception:           # noqa: BLE001
                print(f"!!! AfterHook {hook.name} 异常 !!!\n{traceback.format_exc()}")

    async def _handle_event(self, event) -> None:
        """事件链：与功能链同构 —— 线性扫描，首个 consumed 即停，发送统一走 _emit。"""
        ev_opts = (self.store.effective(event['group_id'])
                   if 'group_id' in event else self.store.global_options.copy())
        outcome = Outcome.pass_()
        for event_handler in self.event_handlers:
            if not event_handler.is_enabled(ev_opts):
                continue
            outcome = await event_handler.handle_event(event)
            if outcome.consumed:
                break
        await self._emit(outcome)

    async def handle(self, event):
        if event['post_type'] == 'message':
            await self._handle_message(event)
        else:
            await self._handle_event(event)
