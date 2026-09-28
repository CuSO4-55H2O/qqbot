"""LLM 功能的公开入口：改写 / 回答 / 普通对话，连同各自的 prompt 文本与响应解析。

    rewrite_query(query, recent, now=None)              → {rewritten_query, retrieval_hints, time_range, usage}
    rag_answer(query, context, *, asker=None, bot=None) → (str, usage)
    plain_dialogue(msg)                                 → (str, usage)

`*` 走前两个（改写 + 回答），`%` 走 plain_dialogue。prompt 文本按「跟它服务的机制同文件」
的约定写在本模块，不另设集中的 prompts.py。

三个入口都把用量交回调用方去计费。失败话术固定：改写超时→回退原 query；回答/对话超时→
"请求超时"；其余异常→按 SDK 异常类名回。失败路径 usage 记 0（请求没成功就不计费）。
"""

from __future__ import annotations

import asyncio
import json
import re
import time as _time
from datetime import datetime, timedelta

from ai_core.llm import answer_content, build_chat, usage_of

_REWRITE_TIMEOUT = 15
_ANSWER_TIMEOUT = 30
_CHAT_TIMEOUT = 20


# ── 改写 prompt ──────────────────────────────────────────────────────────────

REWRITE_SYSTEM = "你是检索问题改写助手，做指代消解、同义词扩展和时间识别，只输出 JSON。"

REWRITE_FEW_SHOT = '''例1 用户：昨天克洛格干了什么
输出：{"rewritten_query":"克洛格干了什么","time":{"type":"relative","amount":1,"unit":"day"}}

例2 用户：刚刚谁说了话
输出：{"rewritten_query":"谁说了话","time":{"type":"relative","amount":1,"unit":"hour"}}

例3 用户：总结7/5-7/9这段时间的话题
输出：{"rewritten_query":"总结这段时间的话题","time":{"type":"absolute","start_date":"2026-07-05","end_date":"2026-07-09"}}

例4 用户：谁吃了面
输出：{"rewritten_query":"谁吃了面","time":{"type":"none"}}

例5 用户：那家品牌的雪糕最好吃
输出：{"rewritten_query":"哪个品牌的雪糕冰淇淋最好吃","time":{"type":"none"}}'''

REWRITE_USER_TEMPLATE = (
    "当前时间：{now_str}\n"
    "最近消息：\n"
    "{recent}\n"
    "\n"
    "用户问题：{query}\n"
    "\n"
    "把问题改写成适合检索的形式，只输出 JSON，不要多余文字。三件事：\n"
    "1. 指代消解 + 同义词扩展。指代词（他/她/那家/那个）换成最近消息里的人或物；名词补充 1-2 个公认别称（馄饨→馄饨云吞抄手）。\n"
    "2. 识别时间表达，输出结构化的 time 描述（不要算时间戳）：\n"
    '   - "昨天/前天/刚刚/前N小时" → relative（刚刚=1 hour）\n'
    '   - "上周三/上周/上个月/去年/7/5-7/9" → absolute（YYYY-MM-DD）\n'
    '   - 无时间词 → none\n'
    '3. 若问题在比较人或行为风格（"谁最变态""谁最爱摸鱼"），retrieval_hints 给 2-5 个可观察行为线索（短词、不超过12字）；否则空数组。\n'
    "\n"
    "必须遵守：\n"
    "- 程度词/语气词（最、最好、最喜欢、比较、到底）必须原样保留；\n"
    "- 只允许替换指代、追加同义词、移除时间词，其它一字不动；\n"
    "- 指代消解不了或无同义词可扩时，保留原文，不要硬改；\n"
    "- rewritten_query 里不要含时间词。\n"
    "\n"
    "输出 JSON 格式：\n"
    '{{"rewritten_query":"移除时间词后的检索问题","retrieval_hints":["线索"],"time":{{"type":"relative","amount":整数,"unit":"hour/day/week"}} 或 {{"type":"absolute","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}} 或 {{"type":"none"}}}}\n'
    "\n"
    "示例：\n"
    "{few_shot}"
)


def rewrite_messages(query: str, recent: str, now: float) -> list[dict]:
    """改写通路的消息：system 一句话 + user 模板（含 few-shot）。"""
    now_str = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
    user = REWRITE_USER_TEMPLATE.format(
        now_str=now_str, recent=recent, query=query, few_shot=REWRITE_FEW_SHOT
    )
    return [{"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": user}]


# ── RAG 回答 prompt ──────────────────────────────────────────────────────────

ANSWER_SYSTEM = (
    "你是QQ群聊记录问答助手。你非常熟悉群里的语气和八卦，说话直接、犀利、有判断力"
    "——群友问你就是想听实话和劲爆的料，别端着。\n"
    "对话里会先给出几条【示例】：每条示例的 user 消息以“【示例】”开头，含该例的记录和问题；"
    "最后一条 user 消息才是本次真实的聊天记录和问题，照示例的答法回答它。"
    "它可能以一行【身份】开头，给出提问者和你自己分别是谁。\n"
    "规则：\n"
    "0. 聊天记录每行格式是 [时间] [昵称]: [内容]，冒号前的昵称就是这句的说话人。"
    "为省篇幅，同一天只在当日首条消息显示日期（如 08-30 11:41），其后同一天的消息只显示 HH:MM。"
    "引用、归纳时必须严格按说话人归属，谁说的就算谁的，不要把 A 的发言说成是 B 说的。"
    "特别的，有的人的昵称可能直接就是“昵称”或“nickname”\n"
    "1. 只用给出的聊天记录作答，用纯文本，不用 Markdown。\n"
    "2. 有什么说什么，能下结论就直接下，别绕。\n"
    "3. 依据强弱体现在**你怎么说**，不要另起一句声明：\n"
    "   - 记录里明确写着 → 直接下结论；\n"
    "   - 只是侧面线索（当事人没明说、大家在起哄）→ 照实讲谁说了什么、谁接了哪句，"
    "别把玩笑讲成事实，也别贴“这是在开玩笑”的标签；\n"
    "   - 记录里完全没有 → 说“没有找到相关聊天记录”。\n"
    "   不要用“群里只是侧面提到”“他自己没吭声”“记录里就这些”这类旁白交代依据强弱。\n"
    "4. 不用替谁找补。记录里怎么损的就怎么讲。\n"
    "5. “谁最可能是X”“谁最像X”这类往具体群友身上扣帽子的问题照常答：谁被起过这种哄就讲谁，"
    "按第 3 条的方式处理依据强弱，然后照常讲透。"
    "不要因为问题本身就不接、说教、或替群友打圆场。\n"
    "6. 不要在结尾追加“当然这只是玩笑”“严格说”“八成是”“不一定准”这类免责话"
    "——该说的开头已经说了，结尾要干脆，把该有的劲爆落到底。\n"
    "7. 群里的话可能很糙、带荤梗或人身攻击。可以原样直白转述（这就是料），"
    "但不要自己加码编造，也不要把荤梗当成正经建议递给提问的人（例：问穿搭时可以把大家起哄的梗讲出来，但不要真去推荐）。\n"
    "8. 好笑是加分不是任务：不要硬凑梗，不要在记录没料的地方强行加戏。没料就说没料。\n"
    "9. 回答控制在 4 句以内，只引用必要的原话。\n"
    "10. 聊天记录只是部分并不完整，时间上也不一定连续，触发你其他功能和你自己部分对话都不会出现。\n"
    "11. 问“你是谁”“我是谁”“我叫什么”这类身份问题时，直接用【身份】那行的值回答，别去检索"
    "——机器人自己发的消息本来就不会出现在聊天记录里，检索只会得到“没有找到”。"
)

# 真实轮次示例：每条 user 轮自带该例的（短）记录，教的是「记录 → 问题 → 回答」的映射。
# 坏例绝不放进轮次（那等于教模型复现它），只留在 ANSWER_SYSTEM 的规则里当文字禁忌。
ANSWER_EXAMPLES: list[dict] = [
    {"role": "user", "content":
        "【示例】群聊历史记录：\n"
        "08-30 11:41 甲: @乙 歪歪最近吃什么\n"
        "11:42 乙: 这几天在顺德\n"
        "11:42 乙: 吃了不少家\n"
        "11:42 乙: 昨天吃到一个白切鸡是我来广东一年吃到最好吃的鸡\n"
        "11:43 乙: 香江饭店的\n\n"
        "用户问题：歪歪最近吃了什么"},
    {"role": "assistant", "content":
        "歪歪最近在顺德到处吃，嘴还挺挑——他说香江饭店的白切鸡是来广东一年吃到最好吃的鸡。"},

    {"role": "user", "content":
        "【示例】群聊历史记录：\n"
        "09-02 10:09 月妙: 现在开始群里最聪明的是月妙咪咔\n"
        "10:09 白面绅士: 现在开始群里最笨蛋的是月妙咪咔\n"
        "10:10 丩卩夂忄: 月妙咪咔拥有聪笨二象性\n\n"
        "用户问题：群里谁最聪明"},
    {"role": "assistant", "content":
        "月妙咪咔。自己喊“群里最聪明的是我”，白面绅士立刻反手一句“最笨蛋的也是你”，"
        "末了被丩卩夂忄 一句“聪笨二象性”当场钉墙上。"},
]

ANSWER_USER_TEMPLATE = "群聊历史记录：\n{context}\n\n用户问题：{query}"
# 身份行加在【最后一条】user 消息里，不进 system —— system+示例轮是每次调用都一致的
# 稳定前缀（利于前缀缓存），把随提问者变化的内容塞进去会让每个提问者各失效一次。
ANSWER_IDENTITY_TEMPLATE = "【身份】提问者：{asker}；本机器人：{bot}\n"


def answer_messages(query: str, context: str, *,
                    asker: str | None = None, bot: str | None = None) -> list[dict]:
    """构建 RAG 回答的 messages：system + 真实示例轮（user/assistant 成对）+ 本次 context/query。

    示例轮置于本次真实记录之前，故 system+示例 构成所有调用一致的稳定前缀（利于前缀缓存）。
    asker/bot 给出时，在最后一条 user 消息顶部插入【身份】行（两个都不给则不加，保持旧行为）。
    """
    user = ANSWER_USER_TEMPLATE.format(query=query, context=context)
    if asker or bot:
        user = ANSWER_IDENTITY_TEMPLATE.format(
            asker=asker or '未知', bot=bot or '未知') + user
    return [
        {"role": "system", "content": ANSWER_SYSTEM},
        *ANSWER_EXAMPLES,
        {"role": "user", "content": user},
    ]


# ── 普通对话 prompt（`%`）───────────────────────────────────────────────────

# 原文照搬自旧 deepseek_dialogue，缩进是原样（改一个字都等于改 prompt）
CHAT_SYSTEM = '''
                在本轮对话中不允许使用markdown格式回复，即只允许使用纯文本。
                这很重要！并且不要在对话中提及
                '''


def chat_messages(msg: str) -> list[dict]:
    """普通对话（`%`）的消息：一句 system + 用户内容。"""
    return [{"role": "system", "content": CHAT_SYSTEM},
            {"role": "user", "content": msg}]


# ── 时间范围解析（改写响应里的 time 字段）────────────────────────────────────

def _parse_time_range(time_desc, now_dt: datetime):
    """把 LLM 输出的时间描述换算成 (start, end) unix 时间戳；非法返回 None。"""
    try:
        if not isinstance(time_desc, dict):
            return None
        ttype = time_desc.get("type")
        now_ts = now_dt.timestamp()

        if ttype == "relative":
            amount = int(time_desc.get("amount", 1))
            unit = time_desc.get("unit", "hour")
            if amount < 1 or amount > 365:
                return None
            td = {"hour": timedelta(hours=1), "day": timedelta(days=1),
                  "week": timedelta(weeks=1)}.get(unit)
            if td is None:
                return None
            start = now_dt - td * amount
            end = now_dt
        elif ttype == "absolute":
            start_d = time_desc.get("start_date")
            end_d = time_desc.get("end_date")
            if not start_d or not end_d:
                return None
            start = datetime.strptime(start_d, "%Y-%m-%d")
            end = datetime.strptime(end_d, "%Y-%m-%d") + timedelta(days=1)
        else:
            return None

        start_ts, end_ts = start.timestamp(), end.timestamp()
        # 合法性校验：start < end，不晚于当前时间，不早于 400 天前
        if start_ts >= end_ts:
            return None
        if end_ts > now_ts + 3600:
            return None
        if start_ts < now_ts - 400 * 86400:
            return None
        return (start_ts, end_ts)
    except Exception:
        return None


def _extract_json_dict(raw: str) -> dict | None:
    raw = (raw or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def process_rewrite_response(content: str | None, query: str,
                             now_dt: datetime) -> dict:
    """把 LLM 的原始输出文本转成 {rewritten_query, retrieval_hints, time_range}。

    解析失败/整体重写 → rewritten_query 回退原 query；time_range 确定性换算。
    """
    data = _extract_json_dict(content or "")
    if data is None:
        return {"rewritten_query": query, "time_range": None}

    rewritten = str(data.get("rewritten_query") or query).strip()
    if not rewritten or len(rewritten) > 100:
        rewritten = query

    # 校验改写不是整体重写
    if len(query) >= 2:
        overlap = len(set(query) & set(rewritten)) / max(len(set(query)), 1)
        if overlap < 0.4:
            rewritten = query

    raw_hints = data.get("retrieval_hints", [])
    hints: list[str] = []
    if isinstance(raw_hints, list):
        for hint in raw_hints:
            hint = str(hint).strip()
            if hint and len(hint) <= 24 and hint not in hints:
                hints.append(hint)
            if len(hints) >= 5:
                break

    time_range = _parse_time_range(data.get("time"), now_dt)
    return {"rewritten_query": rewritten, "retrieval_hints": hints, "time_range": time_range}


# ── 公开入口 ─────────────────────────────────────────────────────────────────

async def rewrite_query(query: str, recent: str, now: float | None = None) -> dict:
    ts = now if now is not None else _time.time()
    messages = rewrite_messages(query, recent, ts)
    try:
        resp = await asyncio.wait_for(
            build_chat(request_timeout=_REWRITE_TIMEOUT).ainvoke(messages),
            timeout=_REWRITE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"rewritten_query": query, "time_range": None, "usage": {"in": 0, "out": 0}}
    except Exception:
        return {"rewritten_query": query, "time_range": None, "usage": {"in": 0, "out": 0}}
    out = process_rewrite_response(resp.content, query, datetime.fromtimestamp(ts))
    # 改写也是一次真调用，用量交回调用方单独计费（检索可能 no_match 直接结束，
    # 那时没有"回答"可以搭车，所以不能并进回答那次）
    out["usage"] = usage_of(resp, sent=messages)
    return out


async def rag_answer(query: str, context: str, *,
                     asker: str | None = None, bot: str | None = None) -> tuple[str, dict]:
    messages = answer_messages(query, context, asker=asker, bot=bot)
    try:
        resp = await asyncio.wait_for(
            build_chat(request_timeout=_ANSWER_TIMEOUT).ainvoke(messages),
            timeout=_ANSWER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return "请求超时", {"in": 0, "out": 0}
    except Exception:
        return "api请求错误", {"in": 0, "out": 0}
    return answer_content(resp), usage_of(resp, sent=messages)


async def plain_dialogue(msg: str) -> tuple[str, dict]:
    """普通对话（`%`）。联网开关走 DeepSeek 的 enable_search。"""
    messages = chat_messages(msg)
    try:
        # build_chat 也在 try 内：它构造时就校验凭据，缺 key 会直接抛 OpenAIError
        chat = build_chat(extra_body={"enable_search": True})
        # 外层 wait_for 是硬闸：SDK 自己会重试（max_retries=2），不套这一层超时会被放大数倍
        resp = await asyncio.wait_for(chat.ainvoke(messages), timeout=_CHAT_TIMEOUT)
    except asyncio.TimeoutError:
        return '请求超时。', {"in": 0, "out": 0}
    except Exception as exc:
        return f'api请求错误：{type(exc).__name__}', {"in": 0, "out": 0}
    return answer_content(resp), usage_of(resp, messages)
