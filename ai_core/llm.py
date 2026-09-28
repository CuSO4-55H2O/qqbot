"""LLM 侧：ChatDeepSeek 访问 + 用量统计。

- 模型调用走官方 partner 包 langchain-deepseek 的 ChatDeepSeek，不手写 AsyncOpenAI SDK。
- 账户接口（余额）是直连 REST，与 langchain 无关，和 `web_search.bocha_search` 同类。
- 用量统计优先用服务端 `usage_metadata`，服务端不给时才按本次发出的消息本地估算。

改写响应的解析不在这里 —— 它唯一的调用者是 `chain.rewrite_query`，跟它同文件。
"""

from __future__ import annotations

import httpx

from constant import DEEPSEEK_API_KEY
from langchain_deepseek import ChatDeepSeek

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


def build_chat(*, request_timeout: float | None = None, model: str = "deepseek-flash",
               **kwargs) -> ChatDeepSeek:
    return ChatDeepSeek(
        model=model,
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        request_timeout=request_timeout,
        **kwargs,
    )


# ── 账户接口（直连 REST）────────────────────────────────────────────────────

async def account_balance():
    """DeepSeek 账户余额。"""
    client = await get_client()
    url = "https://api.deepseek.com/user/balance"
    headers = {
        'Accept': 'application/json',
        'Authorization': 'Bearer '+DEEPSEEK_API_KEY
    }
    response = await client.get(url, headers=headers)
    balance_value = response.json()["balance_infos"][0]["total_balance"]
    return balance_value


# ── 响应与用量 ───────────────────────────────────────────────────────────────

def answer_content(resp) -> str:
    """回答响应取纯文本 content；空/异常给空串。"""
    content = getattr(resp, "content", "") or ""
    return content if isinstance(content, str) else ""


def count_text(text) -> int:
    """本地分词计数；tokenizer 不可用时退化为字符数估算，绝不抛。"""
    text = text if isinstance(text, str) else str(text or "")
    if not text:
        return 0
    try:
        from token_usage import count_tokens
        return count_tokens(text)
    except Exception:
        return max(1, len(text) // 2)


def count_messages(messages) -> int:
    """一组消息的本地 token 估算（dict[role,content] 与 BaseMessage 都支持）。"""
    total = 0
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        total += count_text(c)
    return total


def usage_of(resp, sent=None) -> dict:
    """单次调用的用量 {"in", "out"}。

    优先用服务端返回的 usage_metadata —— 它已含 chat 模板、系统提示、工具 schema
    和 tool_calls 载荷，不用本地再算一遍。服务端没给（或全 0）时，才退回对
    `sent`（本次实际发出的消息/文本）做本地估算。
    """
    um = getattr(resp, "usage_metadata", None) or {}
    try:
        pin = int(um.get("input_tokens") or 0)
        pout = int(um.get("output_tokens") or 0)
    except (TypeError, ValueError):
        pin = pout = 0
    if not (pin or pout):
        pin = count_messages(sent) if sent is not None else 0
        pout = count_text(answer_content(resp))
    return {"in": pin, "out": pout}
