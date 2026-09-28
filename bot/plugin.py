"""插件基类、显式注册表与依赖容器。

构造协议只有一条：`Plugin.__init__(self, deps)`。原先 BotCore 要按类硬编码三个
分支（FeatureAdmin 要 api、FeatureRoulette 要 bot_user_id/…、FeatureChatRAG 要
bot_nickname），而 FeatureSmartRouter 又走了另一套 `attach(bot)` 后门 —— 同一个
问题两套解法。现在两者都归到 `Deps`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.options import AdminAPI
from bot.request import Outcome, Reply, Request
from constant import PluginName


@dataclass
class Deps:
    """组合根（BotCore.init_async）造好后统一发给每个插件。

    **只放有消费者的东西，每个字段注明是谁在用。** 依赖容器是那种「加字段零成本」
    的地方 —— 没有消费者也没东西会挡住它。`store` / `roster` 就这么白放了三个版本，
    直到有人问「是不是所有 feature 都能拿到 AdminAPI」才被翻出来。
    """

    # 机器人自己的身份（启动时 get_login_info 取的）。games 拿它给轮盘传 AI 的
    # id/昵称；events 拿它判断戳一戳的目标是不是自己。
    own_id: int
    own_nickname: str

    # 管理门面：开关功能、黑名单、跨功能调用。**目前只有 FeatureAdmin 一个消费者。**
    # 它是特权对象 —— 功能里要做管理动作别随手拿它，权限用 Request 上的
    # admin / super_admin 自己判。
    api: AdminAPI

    # 全部插件按名字索引。与 AdminAPI 持有的是**同一个可变 dict**：插件构造完再
    # 原地填充，于是插件之间可以互相拿到（智能路由要重派发），又不会在构造期成环。
    plugins: dict[str, "Plugin"] = field(default_factory=dict)


_REGISTRY: list[type["Plugin"]] = []


def register(cls: type["Plugin"]) -> type["Plugin"]:
    """显式注册，取代 `__subclasses__()` 内省。

    内省的隐含前提是「所有功能都住在同一个文件里」—— 一旦按域拆文件，漏掉一个
    import，那个功能就静默消失、不报错。显式注册去掉这个前提，也让启动时能做
    重名与重复优先级的校验。
    """
    _REGISTRY.append(cls)
    return cls


def registered() -> list[type["Plugin"]]:
    return list(_REGISTRY)


class Plugin:
    name: str = None
    priority: int = 100
    plugin_type: str = ''
    abstract: bool = True

    def __init__(self, deps: Deps):
        self.deps = deps

    def is_enabled(self, options: dict) -> bool:
        return options.get(self.name, 0) == 1

    async def reset_cache(self):
        pass


class EventHandler(Plugin):
    plugin_type = PluginName.EVENT_HANDLER
    abstract = True

    async def handle_event(self, event: dict) -> Outcome:
        """返回 Outcome.pass_() 表示不是我的；consumed=True 则事件链就此停下。

        与功能链同构 —— 事件处理器也只返回数据，发送交给 BotCore。
        """
        raise NotImplementedError


class AfterHook(Plugin):
    """功能链跑完之后总能跑到的观察者。

    「没被消费的自然群聊进语料库」这条规则就是个 after-hook：它不认任何触发词，
    只是对**整轮功能链的结果**做观察。原先它内联在 BotCore.handle 里，由那个没有
    任何插件类的 FeatureName.CHAT_RECORD 开关控制 —— 于是它在用户可见的功能列表里，
    却不在插件表里。
    """

    plugin_type = PluginName.AFTER_HOOK
    abstract = True

    async def after(self, req: Request, outcome: Outcome) -> None:
        raise NotImplementedError


class Feature(Plugin):
    plugin_type = PluginName.FEATURE
    abstract = True

    async def function(self, req: Request) -> Outcome:
        raise NotImplementedError

    async def admin_action(self, action: str, **kwargs) -> str:
        return '该功能没有对应的管理功能'


class Matcher(Feature):
    """无状态匹配型功能：看这一条消息就能决定回什么。

    子类只写 `match()`，不再碰 flag / send_msg —— 想回话只能 return。
    「接住了」由返回值表达，所以旧 `Feature.reply` 那个「必须先置 flag、
    顺序反了就静默不发」的陷阱在这里写不出来。

    match() 的返回：
        None              → 没接住，交给下一个功能（Outcome.pass_）
        Reply / Reply 列表 → 接住并回复
        Outcome           → 其它结论（「接住但不回复」用 Outcome.silent()；
                            发 Reply 之外的东西，如贴表情，用 Outcome.handled(EmojiLike(...))）
    """

    async def match(self, req: Request):
        raise NotImplementedError

    async def function(self, req: Request) -> Outcome:
        r = await self.match(req)
        if r is None:
            return Outcome.pass_()
        if isinstance(r, Outcome):
            return r
        if isinstance(r, Reply):
            return Outcome.handled(r)
        replies = tuple(r)
        return Outcome.handled(*replies) if replies else Outcome.pass_()
