from __future__ import annotations

import re
import chat_rag
import token_usage

from dataclasses import replace
from ai_core import agent, chain, llm, retrieve, router
from bot.plugin import Deps, Feature, Matcher, register
from bot.request import Outcome, Reply, Request
from constant import *


@register
class FeatureDeepSeek(Matcher):
    name = FeatureName.DEEPSEEK
    priority = 1
    abstract = False

    async def match(self, req: Request) -> Reply | None:
        msg = req.msg
        if msg.startswith('%%') and len(msg) > 3:
            # 联网搜索（agent 通路）：输入×1 / 输出×3，另按**实际搜索次数**加固定加权
            # —— 博查按次收费，不折算的话这条路的账会严重偏低（搜索才是大头）
            user_content = msg[2:]
            allowed = await token_usage.check_quota(req.qq, req.admin, req.super_admin)
            if not allowed:
                return Reply.same_conversation(req, '今日DeepSeek额度已用完，明天再来吧')
            text, usage = await agent.run_web_agent(user_content)
            await token_usage.add_usage(
                req.qq, usage['in'], usage['out'], 1, 3, source='search', query=user_content,
                bonus_weighted=token_usage.SEARCH_BONUS * usage.get('calls', 0))
            return Reply.same_conversation(req, text)

        if msg.startswith('%') and len(msg) > 2:
            # 普通对话：输入×1 / 输出×3
            user_content = msg[1:]
            allowed = await token_usage.check_quota(req.qq, req.admin, req.super_admin)
            if not allowed:
                return Reply.same_conversation(req, '今日DeepSeek额度已用完，明天再来吧')
            text, usage = await chain.plain_dialogue(user_content)
            await token_usage.add_usage(req.qq, usage['in'], usage['out'], 1, 3,
                                        source='chat', query=user_content)
            return Reply.same_conversation(req, text)

        if msg == '查看余额':
            return Reply.same_conversation(req, await llm.account_balance())

        return None


@register
class FeatureChatRAG(Feature):
    name = FeatureName.CHAT_RAG
    priority = 14
    abstract = False

    async def function(self, req: Request) -> Outcome:
        msg = req.msg
        if not msg.startswith('*') or not req.is_group:
            return Outcome.pass_()

        def done(text: str) -> Outcome:
            return Outcome.handled(Reply.same_conversation(req, text))

        # `**` → agent 聚合通路（tool-calling 全群扫描）；`*` → 原单点检索通路
        use_agent = msg.startswith('**')
        query = (msg[2:] if use_agent else msg[1:]).strip()
        if not query:
            return done('要问什么？')

        # 限额闸放最前：改写是一次 LLM 调用、检索要调嵌入 API，
        # 超限就不该再动任何外部接口。两条路共用这一道。
        if not await token_usage.check_quota(req.qq, req.admin, req.super_admin):
            return done('今日DeepSeek额度已用完，明天再来吧')

        # agent 通路：不做 query 改写，直接进 tool-calling 循环
        if use_agent:
            text, usage = await agent.run_agent(
                req.group_id, query, bot=req.own_nickname, asker=req.nickname)
            await token_usage.add_usage(req.qq, usage['in'], usage['out'], 1, 3,
                                        source='agent', query=query)
            return done(text)

        # Query 改写：指代消解 + 同义词扩展 + 时间范围解析；失败回退原 query
        rewrite_query = query
        time_range = None
        rewrite_usage = {'in': 0, 'out': 0}
        try:
            recent = await chat_rag.recent_context(req.group_id, 10)
            if recent:
                result = await chain.rewrite_query(query, recent)
                rewrite_query = result.get('rewritten_query') or query
                time_range = result.get('time_range')
                rewrite_usage = result.get('usage') or {'in': 0, 'out': 0}
        except Exception:
            pass
        # 改写单独计费：后面检索可能直接 no_match 结束，那次改写就没机会随回答一起记
        await token_usage.add_usage(req.qq, rewrite_usage['in'], rewrite_usage['out'], 1, 3,
                                    source='rewrite', query=query)

        context, status = await retrieve.retrieve_context(req.group_id, rewrite_query, time_range)
        if status == 'empty':
            return done('本群还没有聊天记录')
        if status == 'no_token':
            return done('要问什么？')
        if status == 'no_match':
            return done('没有找到相关信息')
        if status == 'too_sparse':
            return done('那段时间没什么聊天记录')
        if status == 'unavailable':
            return done('RAG 向量服务暂不可用，请检查 DASHSCOPE_API_KEY、DASHSCOPE_BASE_URL 和 Qdrant 服务')

        # RAG 回答：输入×1 / 输出×3。输入 token 连检索文本一起计入。
        text, usage = await chain.rag_answer(query, context, asker=req.nickname,
                                            bot=req.own_nickname)
        await token_usage.add_usage(req.qq, usage['in'], usage['out'], 1, 3,
                                    source='rag', query=query)
        return done(text)


@register
class FeatureSmartRouter(Feature):
    """智能路由：普通消息没被任何精确功能接住时，问 LLM 这句想触发哪个功能，再执行一次。

    单步路由：判定不计配额；被调用的功能走自己的代码路径（配额照算）。排最后（priority=100）。
    规则：内容类(image/dice/bottle/capoo/hsd/op)无需点名；chat 需点名机器人；rag 仅群内。
    """

    name = FeatureName.SMART_ROUTER
    priority = 100
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        # 与 AdminAPI 持有的是同一个 dict：插件构造完由 BotCore 原地填充
        self._feature_map = deps.plugins

    def _image_keys(self) -> list[str]:
        img = self._feature_map.get(FeatureName.IMAGE)
        images = getattr(img, 'images', None)
        return list(images.keys()) if isinstance(images, dict) else []

    @staticmethod
    def _is_addressed(text: str, own_id: int, own_nickname: str) -> bool:
        if not text:
            return False
        if own_nickname and own_nickname in text:
            return True
        if own_id and f"[CQ:at,qq={own_id}" in text:
            return True
        return bool(re.match(r'^\s*(?:ai|AI|机器人)\b', text))

    async def function(self, req: Request) -> Outcome:
        # 能被调到说明整条 feature 链都没消费
        if not self._feature_map or req.msg_type not in (Name.GROUP, Name.PRIVATE):
            return Outcome.pass_()
        text = req.msg.strip()
        if not text:
            return Outcome.pass_()

        addressed = self._is_addressed(req.msg, req.own_id, req.own_nickname)
        plan = await router.smart_route(
            text,
            in_group=req.is_group,
            chat_allowed=addressed,
            image_keys=self._image_keys(),
        )
        target = plan.get('target')
        if not target or target == 'null':
            return Outcome.pass_()

        feature = self._feature_map.get(LLM_TARGETS.get(target))
        if feature is None or not feature.is_enabled(req.options):
            return Outcome.pass_()   # 该功能此群被关（is_enabled=0）→ 不调

        if target == 'chat':
            msg2 = '%' + req.msg
        elif target == 'rag':
            msg2 = '*' + req.msg
        else:
            trigger = (plan.get('trigger') or '').strip()
            if not trigger:
                return Outcome.pass_()
            msg2 = trigger

        # 被调功能走自己的代码路径（配额照算），结论原样上抛
        return await feature.function(replace(req, msg=msg2))
