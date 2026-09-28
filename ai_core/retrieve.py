"""顶层检索编排：群聊候选窗口 → 打分/融合 → 集群压缩 → (context, status)。

顺序即状态机，每一步都可能提前返回：
    空窗(empty/too_sparse) → 无 token(no_token) → 传统路打分 → no_match 门槛
    → 语义路（query 向量 + 窗口向量）→ RRF 种子 → 集群压缩 → 分组文本。
"""

from __future__ import annotations

import asyncio
import time

import chat_rag

from ai_core.bm25 import tokenize
from ai_core.cluster import ClusterCompressor, format_context
from ai_core.config import CANDIDATE_HOURS, CANDIDATE_MAX
from ai_core.data import msgs_to_docs
from ai_core.retrievers import HybridRetriever, QQSparseRetriever
from ai_core.vectorstore import WindowVectorStore


def _fetch_window(group_id: int, time_range, now: float):
    """按群 + 时间窗口取候选（≤CANDIDATE_MAX，id 升序）。空返回 None。"""
    conn = chat_rag._connect()
    try:
        if time_range:
            start, end = time_range
            rows = conn.execute(
                "SELECT * FROM chat_history WHERE group_id=? AND time>=? AND time<? "
                "ORDER BY id DESC LIMIT ?",
                (group_id, start, end, CANDIDATE_MAX),
            ).fetchall()
        else:
            cutoff = now - CANDIDATE_HOURS * 3600
            rows = conn.execute(
                "SELECT * FROM chat_history WHERE group_id=? AND time>? "
                "ORDER BY id DESC LIMIT ?",
                (group_id, cutoff, CANDIDATE_MAX),
            ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    messages = [dict(r) for r in rows]
    messages.reverse()
    return messages


def _retrieve_sync(group_id: int, query: str, time_range,
                   now: float) -> tuple[str | None, str]:
    msgs = _fetch_window(group_id, time_range, now)
    if msgs is None:
        return None, ("too_sparse" if time_range else "empty")

    query_tokens = tokenize(query)
    if not query_tokens:
        return None, "no_token"

    docs = msgs_to_docs(msgs)
    # 同一个人改过名时，历史行里存的是当时的昵称。这里统一显示成最新昵称，
    # 免得模型把一个人当成两个人；库里的原始昵称不动，历史仍可追。
    current, alias_to_current = chat_rag._identity_sync(group_id)
    for d in docs:
        uin = int(d.metadata["uin"])
        if uin in current:
            d.metadata["name"] = current[uin]

    sparse = QQSparseRetriever(docs, alias_to_current)

    # no_match 门槛：仅看传统路最高分（语义路不计入，防硬救回关键词全无命中的查询）
    if max(sparse.score_all(query, query_tokens, now), default=0.0) <= 0:
        return None, "no_match"

    # 语义路只在过门槛后才取向量，避免白花一次嵌入 API / DB 开销
    qv = chat_rag._embed_query_vec(query)
    vec_map = chat_rag._embed_doc_vecs(group_id, msgs) if qv is not None else None

    store = WindowVectorStore(docs, vec_map)
    hybrid = HybridRetriever(sparse, store, now=now)
    sem_enabled = qv is not None and vec_map is not None
    seeds, rrf = hybrid.fuse(query, query_tokens, qv, sem_enabled=sem_enabled)

    compressor = ClusterCompressor(docs, seeds, rrf, vec_map)
    kept = compressor.compress_documents(docs)
    return format_context(kept), "ok"


async def retrieve_context(group_id: int, query: str, time_range=None, *,
                           now: float | None = None) -> tuple[str | None, str]:
    """异步检索入口（bot.core 直接调用）。"""
    ts = now if now is not None else time.time()
    return await asyncio.to_thread(_retrieve_sync, group_id, query, time_range, ts)
