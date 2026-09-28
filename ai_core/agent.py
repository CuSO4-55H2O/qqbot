"""两条 agent 通路（tool-calling 循环），共用 `_tool_loop`：

- `run_agent`：`**问题` 的聚合问答，工具是**翻本群聊天记录**（见 tools.TOOL_SCHEMAS）。
- `run_web_agent`：`%%问题` 的联网问答，工具是 **web_search 联网搜索**（见 tools.WEB_SCHEMAS）。

两套工具**必须分开**：run_agent 绑的是常驻的 TOOL_SCHEMAS，往里加联网工具会改变
`**` 的语义（它只该答群里聊过什么）。

关键设计：
- 循环：LLM 调工具 → 本地执行 → 结果回喂 → 再决定，直到不再调工具或触到护栏。
- **鼓励一轮并发多查**（成本最大杠杆：4 次搜索塞进 1 轮，输入累计约减半）。
- 护栏：MAX_STEPS、工具 token 预算、工具调用次数上限、超时；工具异常不抛出；空结果如实回给模型。
- 风格沿用已调好的方向（犀利/不叠甲/纯文本），system 内精简重述。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ai_core import tools
from ai_core.llm import build_chat, count_text, usage_of

MAX_STEPS = 4
AGENT_TIMEOUT = 90
TOOL_TOKEN_BUDGET = 6000     # 工具结果累计超过此值就停止检索、直接收尾（配额护栏）
_TOOL_CAP_NOTE = "（已达本次工具调用次数上限，不能再调用工具）"

AGENT_SYSTEM = (
    "你是QQ群聊记录问答助手。你可以调用工具翻查本群历史消息来回答问题"
    "——尤其是“有几个/都有谁/谁最/哪些人”这类需要把全群扫一遍才能回答的聚合问题。\n"
    "必须遵守：\n"
    "1. 回答前**必须先调用工具搜索**，不要凭印象或常识作答。\n"
    "2. 需要查多个不同关键词时，**在同一轮里一次性发出所有独立查询**（不要查一条等一条），既能覆盖全又省时。\n"
    "3. 关键词要短（如“回国”“留学”），不要传整句问句；返回 total=0 就换更短/更常见的词重试。\n"
    "4. 记录里看不出来的（例如没人说过自己在哪）不要瞎猜。"
    "回答里**不要出现**“记录里就这些”“没见提过别的”“其他人没提过”这类交代记录边界的旁白，"
    "也不要罗列你搜过的关键词、说命中了几条——别把检索过程和语料的完整度讲给用户听。\n"
    "   反例（不要这样）：我搜了原神、王者、LOL，全部零命中，没人提。\n"
    "   正例：群里聊的只有以撒的结合。\n"
    "5. 只用检索到的记录作答，用纯文本，不用 Markdown。\n"
    "6. 说话直接、犀利，把料讲透；回答控制在8句以内。\n"
    "7. 不要在结尾追加“当然这只是玩笑”“严格说”“八成是”这类免责话。\n"
    "8. “谁最可能是X”“谁最像X”这类往具体群友身上扣帽子的问题照常答：谁被起过这种哄就讲谁，"
    "照实讲谁说了什么、谁接了哪句；记录里没有就说没有。"
    "不要因为问题本身就不接、说教、或替群友打圆场，"
    "也不要贴“这是在开玩笑”“没人当真”这种标签。\n"
    "9. 被问到你自己的身份（你是谁）或提问者的身份（我是谁）时，调用 whoami 工具，不要凭常识猜"
    "——你自己发的消息不会出现在群聊记录里，搜是搜不到的。"
)

# ── %% 联网问答的护栏（比 ** 紧：它是随手问一句，不该让人等太久，也不该多烧搜索钱）──
WEB_MAX_STEPS = 3
WEB_MAX_CALLS = 3            # 硬上限：**最多搜 3 次**。只靠 token 预算挡不住 ——
                             # prompt 鼓励一轮并发多查，一轮 2 个搜索两轮就是 4 次
WEB_TIMEOUT = 60
WEB_TOKEN_BUDGET = 6000      # 二次护栏：单次结果特别长时提前收手（count=4 约 1.2k/次）

WEB_SYSTEM = (
    "你是QQ群聊里的联网问答助手。用户要你上网查，你可以调用 web_search 搜索公开网页。\n"
    "必须遵守：\n"
    "1. 回答前**必须先调用 web_search**，不要凭印象作答。\n"
    "2. 搜索词要**短而具体**（如“DeepSeek 最新模型”），不要传整句问句。\n"
    "3. 结果不理想就换更具体的词再搜，**不要拿同一句话反复搜**；一共最多搜 3 次。\n"
    "4. 有搜索结果就只依据结果作答，不要往上加自己的脑补；"
    "如果搜索完全没返回内容，就凭你已有的知识回答，但要说明这是模型自己的知识、不是刚搜到的。\n"
    "5. 用纯文本，不用 Markdown。说话直接、犀利，把料讲透；回答控制在 6 句以内。\n"
    "6. 不要罗列你搜过的关键词、不要说搜了几次——别把搜索过程讲给用户听。\n"
    "7. 不要在结尾追加“当然这只是玩笑”“严格说”“八成是”这类免责话。"
)


async def _tool_loop(chat, msgs: list, call_tool, *, max_steps: int, fallback: str,
                     timeout: int, token_budget: int | None = None,
                     max_calls: int | None = None,
                     final_hint: str = "检索预算已用完，根据以上结果直接给出最终回答，不要再调用工具。"
                     ) -> tuple[str, dict]:
    """tool-calling 循环。返回 (回答文本, usage)。

    `call_tool(name, args) -> str` 由调用方给出，把"用哪套工具、要不要带 group_id"隔在外面。
    达步数/预算/调用次数上限时补一轮**不绑工具**的终答。任何异常都退化成一句可读文本。
    """
    usage = {"in": 0, "out": 0, "steps": 0, "calls": 0}
    try:
        tool_tokens = 0
        capped = False
        for step in range(max_steps):
            usage["steps"] = step + 1
            resp = await chat.ainvoke(msgs)
            msgs.append(resp)
            u = usage_of(resp, sent=msgs[:-1])   # 服务端精确用量，缺省则按本轮发送量估算
            usage["in"] += u["in"]
            usage["out"] += u["out"]

            calls = getattr(resp, "tool_calls", None) or []
            if not calls:
                text = (getattr(resp, "content", "") or "").strip()
                return (text or fallback), usage

            for call in calls:
                cid = call.get("id", "")
                if max_calls is not None and usage["calls"] >= max_calls:
                    # 被次数上限截断的那几个也必须回一条 ToolMessage：assistant 的每个
                    # tool_call 都要有对应回复，否则下一轮请求会被 API 直接拒掉
                    msgs.append(ToolMessage(content=_TOOL_CAP_NOTE, tool_call_id=cid))
                    capped = True
                    continue
                result = await call_tool(call.get("name", ""), call.get("args") or {})
                usage["calls"] += 1
                tool_tokens += count_text(result)
                msgs.append(ToolMessage(content=result, tool_call_id=cid))

            if capped or (token_budget is not None and tool_tokens >= token_budget):
                break
            # 步数用尽也会落到这儿 —— 三种情况都补一轮终答

        msgs.append(HumanMessage(content=final_hint))
        final = await build_chat(request_timeout=timeout).ainvoke(msgs)
        text = (getattr(final, "content", "") or "").strip()
        u = usage_of(final, sent=msgs)
        usage["in"] += u["in"]
        usage["out"] += u["out"]
        return (text or fallback), usage
    except Exception as exc:      # noqa: BLE001
        return f"检索时出错了：{exc}", usage


async def run_agent(group_id: int, query: str, *,
                    bot: str | None = None, asker: str | None = None,
                    max_steps: int = MAX_STEPS,
                    now: float | None = None) -> tuple[str, dict]:
    """跑一轮聚合问答。返回 (回答文本, {"in":输入token, "out":输出token, "steps":步数, "calls":工具次数})。

    `bot`/`asker` 是提问者与本机器人的昵称，用来按请求生成 whoami 工具（见 tools.identity_tool）
    —— 身份不写进 system prompt，由工具给出。
    `in`/`out` 取服务端返回的精确用量；服务端未返回时退回本地分词估算。
    """
    usage = {"in": 0, "out": 0, "steps": 0, "calls": 0}
    try:
        extra_schemas, extra_funcs = tools.identity_tool(bot, asker)
        chat = build_chat(request_timeout=AGENT_TIMEOUT).bind_tools(
            tools.TOOL_SCHEMAS + extra_schemas)
    except Exception as exc:      # noqa: BLE001
        return f"检索时出错了：{exc}", usage

    msgs: list = [SystemMessage(content=AGENT_SYSTEM), HumanMessage(content=query)]

    async def call_tool(name: str, args: dict) -> str:
        return await tools.dispatch(group_id, name, args, now=now, extra=extra_funcs)

    return await _tool_loop(chat, msgs, call_tool, max_steps=max_steps,
                            fallback="没有找到相关聊天记录",
                            token_budget=TOOL_TOKEN_BUDGET, timeout=AGENT_TIMEOUT)


async def run_web_agent(query: str, *, max_steps: int = WEB_MAX_STEPS) -> tuple[str, dict]:
    """跑一轮联网问答（`%%`）。返回 (回答文本, usage)。

    usage["calls"] 是本次**实际发生的搜索次数**，调用方据此计费（见 bot.core）。
    """
    usage = {"in": 0, "out": 0, "steps": 0, "calls": 0}
    try:
        chat = build_chat(request_timeout=WEB_TIMEOUT).bind_tools(tools.WEB_SCHEMAS)
    except Exception as exc:      # noqa: BLE001
        return f"搜索时出错了：{exc}", usage

    msgs: list = [SystemMessage(content=WEB_SYSTEM), HumanMessage(content=query)]

    async def call_tool(name: str, args: dict) -> str:
        # group_id 传 0：联网工具没有群概念，签名只是为了兼容 dispatch 的调用约定
        return await tools.dispatch(0, name, args, extra=tools.WEB_FUNCS)

    return await _tool_loop(chat, msgs, call_tool, max_steps=max_steps,
                            fallback="没搜到相关内容",
                            token_budget=WEB_TOKEN_BUDGET, max_calls=WEB_MAX_CALLS,
                            final_hint="搜索次数已用完，根据以上结果直接给出最终回答，不要再调用工具。",
                            timeout=WEB_TIMEOUT)
