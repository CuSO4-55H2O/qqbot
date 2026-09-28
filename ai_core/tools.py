"""聚合检索的只读工具（agent 通路专用）。

设计要点：
- **只读**：只走 SELECT，不给裸 SQL；工具入参是关键词，不是查询语句。
- **以单条消息为匹配单位**（不像单点检索那样做话题簇扩散）——聚合要的是"谁的哪句话"。
- 命中条默认带 ±CONTEXT 条上下文（群聊短句 + 指代，孤立单条常读不懂），命中条用 ● 标出。
- 返回带 total/offset，模型据此判断该翻页还是换词，而不是以为"就这几条"。
- 关键词 OR 匹配；命中 0 也要如实返回 total=0，好让模型换个说法再试。
"""

from __future__ import annotations

import inspect
import re
import time as _time

import chat_rag

from ai_core.config import CANDIDATE_HOURS
from ai_core.web_search import bocha_search

CONTEXT_LINES = 1        # 命中条上下各带几条
MAX_CONTENT = 120        # 单条内容截断
DEFAULT_LIMIT = 20
MAX_LIMIT = 20           # 聚合扫描靠"多轮换词"，不靠单次返回多；上限压小以控 token


def _split_terms(query: str) -> list[str]:
    """把工具入参拆成关键词（空格/逗号/顿号分隔），过滤空串。"""
    parts = re.split(r"[\s,，、]+", (query or "").strip())
    return [p for p in parts if p]


def _fetch_msgs(group_id: int, now: float | None = None) -> list[dict]:
    """取该群候选窗（id 升序）。与单点检索同一取数口径。"""
    ts = now if now is not None else _time.time()
    cutoff = ts - CANDIDATE_HOURS * 3600
    conn = chat_rag._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_history WHERE group_id=? AND time>? ORDER BY id",
            (group_id, cutoff),
        ).fetchall()
    finally:
        conn.close()
    msgs = [dict(r) for r in rows]
    # 改过名的人，展示统一用最新昵称（库里存的仍是当时的昵称）
    current = chat_rag._identity_sync(group_id)[0]
    if current:
        for m in msgs:
            m["name"] = current.get(int(m["uin"]), m["name"])
    return msgs


def _line(msg: dict, hit: bool) -> str:
    mark = "●" if hit else " "
    t = _time.strftime("%m-%d %H:%M", _time.localtime(msg["time"]))
    content = (msg["content"] or "")[:MAX_CONTENT]
    return f"{mark} #{msg['id']} {t} {msg['name']}: {content}"


def search_messages(group_id: int, query: str, limit: int = DEFAULT_LIMIT,
                    offset: int = 0, context: int = CONTEXT_LINES,
                    now: float | None = None) -> str:
    """按关键词 OR 扫描该群消息，返回命中条（含少量上下文）。"""
    terms = _split_terms(query)
    if not terms:
        return "（未提供关键词）"

    msgs = _fetch_msgs(group_id, now)
    if not msgs:
        return "该群没有聊天记录。"

    hits = [i for i, m in enumerate(msgs) if any(t in (m["content"] or "") for t in terms)]
    total = len(hits)
    if total == 0:
        return (f"total=0（关键词 {terms} 无任何命中）。"
                f"请换更短或更常见的词再试。")

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    # 命中按时间【倒序】分页：这类问题（谁在哪/谁最近提过）多数问当前状态，
    # 最新证据最相关；offset 语义 = 往更早的方向翻第 N 批。
    page_desc = hits[::-1][offset: offset + limit]
    if not page_desc:
        return f"total={total}，但 offset={offset} 已超出范围。"
    page = sorted(page_desc)          # 页内仍按时间升序展示、便于顺读

    ctx = max(0, min(int(context if context is not None else CONTEXT_LINES), 3))
    # 命中 + 上下文的行区间，合并重叠
    spans: list[list[int]] = []
    for h in page:
        lo, hi = max(0, h - ctx), min(len(msgs) - 1, h + ctx)
        if spans and lo <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    hit_set = set(page)
    lines = [
        f"{_line(msgs[i], i in hit_set)}"
        for lo, hi in spans for i in range(lo, hi + 1)
    ]

    def _d(i: int) -> str:
        return _time.strftime("%m-%d", _time.localtime(msgs[i]["time"]))

    header = (f"total={total} 本次显示={len(page)} offset={offset} "
              f"（关键词 {terms}；命中整体跨度 {_d(hits[0])}~{_d(hits[-1])}，"
              f"本页 {_d(page[0])}~{_d(page[-1])}，取的是【最新】一批；"
              f"● 为命中条，其余为上下文）")
    # 命中远多于本页时必须显式警告：否则模型会把"这一页"当成"全部"，静默漏报。
    warn = ""
    if total > len(page):
        warn = (f"\n⚠ 命中 {total} 条，本页只是最新/靠后的 {len(page)} 条，**绝不是全部**。"
                f"不要据此下结论：请改用更具体的关键词（单个地名/人名）缩小，"
                f"或用 offset={offset + len(page)} 继续往更早翻。")
    tail = ""
    if offset + len(page) < total:
        tail = f"\n（还有 {total - offset - len(page)} 条更早的，可用 offset={offset + len(page)} 继续取）"
    return header + warn + "\n" + "\n".join(lines) + tail


def count_by(group_id: int, keyword: str, now: float | None = None) -> str:
    """统计含关键词的消息总数，并按说话人给出计数（谁说得最多）。"""
    terms = _split_terms(keyword)
    if not terms:
        return "（未提供关键词）"

    msgs = _fetch_msgs(group_id, now)
    if not msgs:
        return "该群没有聊天记录。"

    hits = [m for m in msgs if any(t in (m["content"] or "") for t in terms)]
    if not hits:
        return f"total=0（关键词 {terms} 无命中）。"

    # 按 uin 计数：昵称只是标签，改过名不能被拆成两个"人"，撞名也不能并成一个
    by_uin: dict[int, int] = {}
    label: dict[int, str] = {}
    for m in hits:
        uin = int(m["uin"])
        by_uin[uin] = by_uin.get(uin, 0) + 1
        label[uin] = m["name"]
    top = sorted(by_uin.items(), key=lambda kv: kv[1], reverse=True)[:10]
    detail = "、".join(f"{label[u]}×{c}" for u, c in top)
    return f"total={len(hits)}（关键词 {terms}）\n按说话人：{detail}"


# ── 供 LLM function-calling 用的 schema（OpenAI 风格）────────────────────────
TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "search_messages",
        "description": ("按关键词扫描该 QQ 群的历史消息，返回命中的单条消息（含少量上下文）。"
                        "用于\"谁提过X\"\"谁在哪里\"\"有没有聊过X\"这类需要翻找全群的问题。"
                        "命中多于 limit 时，**优先返回最新的那一批**，可用 offset 往更早翻。"
                        "query 传**短关键词**（可空格分隔多个，任一命中即可），不要传整句问句；"
                        "若返回 total=0，请换更短/更常见的词重试。"),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "关键词，多个用空格分隔，如：回国 出国 留学"},
            "limit": {"type": "integer", "description": "本页返回多少条命中（默认20，最大20）"},
            "offset": {"type": "integer", "description": "翻页偏移，默认0"},
            "context": {"type": "integer", "description": "每条命中附带上下各几条（默认1，0为不带）"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "count_by",
        "description": ("统计含某关键词的消息条数，并给出按说话人的计数（谁说得最多）。"
                        "适合\"有多少人提过X\"\"谁最常提X\"这类统计问题。"),
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "关键词，多个用空格分隔"},
        }, "required": ["keyword"]}}},
]

# 工具名 → 实现
TOOL_FUNCS = {
    "search_messages": search_messages,
    "count_by": count_by,
}

# 各工具的合法参数名（模型给了多余/错名参数时按此剥离重试）
_TOOL_ARGS = {
    "search_messages": ("query", "limit", "offset", "context"),
    "count_by": ("keyword",),
    "web_search": ("query", "count"),
}


# ── 联网搜索工具：只给 %% 的 agent，不进 TOOL_SCHEMAS ────────────────────────
# 绝不能加进常驻的 TOOL_SCHEMAS：run_agent（**）绑的就是它，** 是"翻本群记录"，
# 多出一个联网工具会改变那条路的语义。

WEB_DEFAULT_COUNT = 4
WEB_MAX_COUNT = 8


async def web_search(group_id: int, query: str, count: int = WEB_DEFAULT_COUNT,
                     now: float | None = None, **_ignored) -> str:
    """联网搜索。group_id 只为兼容 dispatch 的调用约定，这里用不到。"""
    q = (query or "").strip()
    if not q:
        return "（未提供搜索词）"
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = WEB_DEFAULT_COUNT
    n = max(1, min(n, WEB_MAX_COUNT))

    text = await bocha_search(q, count=n)
    if text:
        return text
    # bocha_search 把"没搜到"和"服务挂了"都吞成空串，这里只能给一句模糊的话；
    # 关键是让模型知道**该换词或该收手**，而不是原地重试到烧完步数。
    return ("（联网搜索没有返回任何内容——可能是这个词搜不到，也可能是搜索服务暂时不可用。"
            "请换一个更常见的关键词再试一次；如果还是空的，就直接凭你已有的知识回答。）")


WEB_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": ("联网搜索公开网页，返回若干条结果的标题、摘要和来源链接。"
                        "用于需要**当前/外部事实**的问题（新闻、时效数据、公开资料），"
                        "群里聊过的内容不要用它，那是另一个工具的活。"
                        "query 传**短而具体**的关键词（如\"DeepSeek 最新模型\"），不要传整句问句；"
                        "结果不理想就换更具体的词再搜，不要用同一句话反复搜。"),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词，短而具体"},
            "count": {"type": "integer",
                      "description": f"返回几条结果（默认{WEB_DEFAULT_COUNT}，最大{WEB_MAX_COUNT}）"},
        }, "required": ["query"]}}},
]

WEB_FUNCS = {"web_search": web_search}


def identity_tool(bot_nick: str | None, asker_nick: str | None) -> tuple[list[dict], dict]:
    """按请求生成「身份」工具，返回 (schema 列表, 实现映射)。

    身份随提问者变化，又不能在模块级存全局状态 —— bot 并发处理多个群的消息，
    全局变量会串号。所以按请求造一份，和 chat 的 bind_tools 一起用，不进 TOOL_SCHEMAS。
    """
    text = f"提问者：{asker_nick or '未知'}\n本机器人：{bot_nick or '未知'}"
    schema = [{"type": "function", "function": {
        "name": "whoami",
        "description": ("返回提问者是谁、以及你自己（本机器人）是谁。"
                        "被问到「你是谁」「我是谁」「我叫什么」这类身份问题时调用，不要凭常识猜。"),
        "parameters": {"type": "object", "properties": {}}}}]

    def whoami(group_id: int, **_ignored) -> str:
        return text

    return schema, {"whoami": whoami}


async def _run_tool(fn, group_id: int, args: dict, now):
    """调用工具函数。群聊工具是同步的，联网工具是 async 的，两种都吃。"""
    result = fn(group_id, **(args or {}), now=now)
    return await result if inspect.isawaitable(result) else result


async def dispatch(group_id: int, name: str, args: dict, now: float | None = None,
                   extra: dict | None = None) -> str:
    """执行一次工具调用。未知工具/异常都返回可读文本，不抛给循环。

    extra 是按请求生成的工具（如身份类），优先于常驻工具表。
    """
    fn = (extra or {}).get(name) or TOOL_FUNCS.get(name)
    if fn is None:
        return f"（未知工具：{name}）"
    try:
        return await _run_tool(fn, group_id, args, now)
    except TypeError:
        # 模型给了多余/错误参数：剥掉再试一次
        sig = _TOOL_ARGS.get(name)
        if sig is None:
            return f"（工具执行失败：{name} 的参数不对）"
        try:
            clean = {k: v for k, v in (args or {}).items() if k in sig}
            return await _run_tool(fn, group_id, clean, now)
        except Exception as exc:      # noqa: BLE001
            return f"（工具执行失败：{exc}）"
    except Exception as exc:          # noqa: BLE001
        return f"（工具执行失败：{exc}）"
