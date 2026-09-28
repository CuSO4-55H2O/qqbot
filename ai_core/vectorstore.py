"""窗口型语义打分：对一个已加载的候选窗口给出余弦分数。

设计取舍：LangChain 的 VectorStore 假设"常驻索引"（文档加进去、随时查），而群聊检索是
"每次查询取该群近 N 条"的窗口语义 —— 两者不匹配，所以这里只做窗口只读视图。

cosine_scores() 返回**与窗口对齐的全量**余弦（RRF 要的是每条消息的名次，不是 top-k）；
缺向量的位置为 0.0。向量的 SQLite BLOB 持久读写仍由 chat_rag 承担，本类只持内存视图。
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from langchain_core.documents import Document


def _cosine_sim(a_vec, b_vec) -> float:
    """numpy 余弦相似度（原始值）。任一侧缺失返回 0.0。"""
    if a_vec is None or b_vec is None:
        return 0.0
    try:
        a = np.asarray(a_vec, dtype=np.float32)
        b = np.asarray(b_vec, dtype=np.float32)
        if a.size == 0 or b.size == 0:
            return 0.0
        an = float(np.linalg.norm(a))
        bn = float(np.linalg.norm(b))
        if an == 0 or bn == 0:
            return 0.0
        return float(np.dot(a, b) / (an * bn))
    except Exception:
        return 0.0


class WindowVectorStore:
    """窗口型只读语义检索：docs 顺序即候选窗口顺序（id 升序）。"""

    def __init__(self, docs: Sequence[Document],
                 vec_map: dict[int, Any] | None = None) -> None:
        self.docs = list(docs)
        vec_map = vec_map or {}
        self._aligned = [vec_map.get(int(d.metadata["id"])) for d in self.docs]

    def cosine_scores(self, query_vec) -> list[float]:
        """返回与 self.docs 对齐的余弦相似度列表；缺向量位置为 0.0。"""
        return [_cosine_sim(query_vec, v) for v in self._aligned]
