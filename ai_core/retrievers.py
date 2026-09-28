"""检索打分的两个原语：逐条消息的传统路打分，以及双路 RRF 融合。

- QQSparseRetriever.score_all()：给窗口里每条消息打一个传统路分
  （w1 BM25 + w3 实体命中 + w4 说话人提权 + 长度惩罚），公式在 bm25.score_message。
- rrf_fuse()：把传统路 / 语义路两路的排名融合成一个种子顺序。
- HybridRetriever.fuse()：取两路分数后交给 rrf_fuse。

三者由 retrieve.py 的 _retrieve_sync 直接调用，本模块不实现 LangChain 的召回器接口。
调优常量在 ai_core/config.py。
"""

from __future__ import annotations

import time
from typing import Sequence

from langchain_core.documents import Document

from ai_core.bm25 import BM25, detect_target_names, score_message
from ai_core.config import RRF_K, SEED_K, SEM_SEED_K, SEM_SEED_MIN
from ai_core.vectorstore import WindowVectorStore


class QQSparseRetriever:
    """传统路打分器：窗口内多因子打分（w1 BM25 + w3 实体 + w4 说话人 + 长度惩罚）。"""

    def __init__(self, docs: Sequence[Document],
                 alias_to_current: dict[str, str] | None = None) -> None:
        self.docs = list(docs)
        contents = [d.page_content for d in self.docs]
        self._bm25 = BM25(contents)
        self._names = list({d.metadata["name"] for d in self.docs})
        # 该群「用过的旧昵称 → 最新昵称」：拿旧名提问时也要能提权到本人。
        # 窗口里的 name 已被 retrieve 规范化成最新昵称，所以这里只需补查旧名。
        self._alias_to_current = alias_to_current or {}

    def score_all(self, query: str, query_tokens: list[str], now: float) -> list[float]:
        """返回与窗口对齐的传统路分数列表（逐元素同 score_message）。"""
        targets = detect_target_names(query, self._names)
        for alias, cur in self._alias_to_current.items():
            if len(alias) >= 2 and alias in query:
                targets.add(cur)
        return [
            score_message(
                d.page_content, self._bm25, i, query_tokens, query,
                now, targets, d.metadata["name"],
            )
            for i, d in enumerate(self.docs)
        ]


def rrf_fuse(trad_scores: list[float], sem_scores: list[float] | None, *,
             sem_enabled: bool) -> tuple[list[int], dict[int, float]]:
    """双路种子并集 + RRF 计权 + 按融合分降序。

    仅"入过某路 top-k 的种子"计分；每路按**全窗排名**计 RRF 权重（种子在对方路的
    排名同样贡献，故需要全量排名而非仅 top-k）。返回 (seeds下标列表, rrf分 dict)。
    """
    n = len(trad_scores)
    trad_ranked = sorted(range(n), key=lambda i: trad_scores[i], reverse=True)
    sem_ranked = (
        sorted(range(n), key=lambda i: sem_scores[i], reverse=True) if sem_enabled else []
    )

    seed_union = set(trad_ranked[: SEED_K])
    if sem_ranked:
        for i in sem_ranked[: SEM_SEED_K]:
            # 向量缺失的位置余弦为 0 < 阈值，所以这一个条件同时表达了"有向量且过阈值"
            if sem_scores[i] >= SEM_SEED_MIN:
                seed_union.add(i)

    rrf: dict[int, float] = {}
    for rank, i in enumerate(trad_ranked):
        if i in seed_union:
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (RRF_K + rank)
    for rank, i in enumerate(sem_ranked):
        if i in seed_union:
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (RRF_K + rank)
    seeds = sorted(seed_union, key=lambda i: rrf[i], reverse=True)
    return seeds, rrf


class HybridRetriever:
    """组合检索：传统路 + 语义路 → RRF 融合出种子。

    仅需要"某路分数/向量就绪"时走真实双路；无语义（无 API key / 无向量）退纯传统路。
    """

    def __init__(self, sparse: QQSparseRetriever, store: WindowVectorStore | None,
                 *, now: float | None = None) -> None:
        self.sparse = sparse
        self.store = store
        self.now = now if now is not None else time.time()

    def fuse(self, query: str, query_tokens: list[str], query_vec,
             *, sem_enabled: bool) -> tuple[list[int], dict[int, float]]:
        """算种子与 RRF 分。sem_enabled 由调用方判定（query_vec 且窗口有向量），
        语义不可用时 sem_scores=None → 纯传统路。"""
        trad_scores = self.sparse.score_all(query, query_tokens, self.now)
        sem_scores = (
            self.store.cosine_scores(query_vec)
            if sem_enabled and self.store is not None else None
        )
        return rrf_fuse(trad_scores, sem_scores, sem_enabled=sem_enabled)
