"""博查（Bocha）联网搜索：agent 的 `web_search` 工具背后的实现。

第三方 REST 调用，与 LLM SDK 无关，和 `llm.account_balance` 同类。
按能力单独一个模块：`tools.py` 里的 `web_search` 只是面向模型的壳，
真正的 HTTP 与解析在这里；不塞进 `tools.py` 是因为那个模块是群聊记录工具的领地。
"""

from __future__ import annotations

import asyncio

import httpx

from constant import BOCHA_API_KEY

_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
_TIMEOUT = 15.0

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


async def bocha_search(query: str, count: int = 5) -> str:
    """搜索网页，返回格式化的文本结果。

    超时、非 200、无结果**都静默返回空串**（沿用原实现）。所以调用方无法区分
    "没搜到"和"接口挂了"——工具层据此给模型一句模糊的话，见 tools.web_search。
    """
    client = await _get_client()
    headers = {
        "Authorization": f"Bearer {BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "count": count, "summary": True}
    try:
        response = await asyncio.wait_for(
            client.post(_SEARCH_URL, headers=headers, json=payload),
            timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return ""
    if response.status_code != 200:
        return ""

    data = response.json()
    pages = data.get("data", {}).get("webPages", {}).get("value", [])
    if not pages:
        return ""

    lines = []
    for i, p in enumerate(pages):
        title = p.get("name", "")
        url = p.get("url", "")
        snippet = p.get("summary") or p.get("snippet", "")
        lines.append(f"[{i + 1}] {title}\n    {snippet}\n    来源: {url}")
    return "\n\n".join(lines)
