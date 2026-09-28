"""检索后处理：对话集群提取、选择与分组输出。

把"检索命中的零散消息"压成"进入上下文的一段段对话"：同一话题的多条消息归成一段，
结果仍以 Document 列表返回，每份带 metadata["_block"] 与 ["_seq"]，供格式化步骤重建分组。

对话集群扩展（_expand_cluster：同人豁免 / 时间闸 / 锚点语义扩展 / 连续失败停）
与集群排序 / 裁剪 / 分组尾段都在本模块。
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from pydantic import ConfigDict

from ai_core.config import (
    CLUSTER_MAX,
    EXPAND_FAIL_LIMIT,
    MAX_RETRIEVE_LEN,
    OUTPUT_TOP,
    RECENT_N,
    SEM_ANCHOR_WEIGHTS,
    SEM_EXPAND_MIN,
    SIM_THRESHOLD,
    TOKEN_BUDGET,
    WINDOW,
)
from ai_core.data import docs_to_msgs
from ai_core.vectorstore import _cosine_sim


# ── 对话集群扩展 ──────────────────────────────────────────────────────────────


def _char_sim(a: str, b: str) -> float:
    """字符集 Jaccard 相似度，用于话题跳变判断。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _expand_cluster(messages: list[dict], seed_idx: int, window_times: list[float],
                    vecs: dict[int, object] | None = None) -> list[int]:
    """以种子为中心，无条件纳入前后各 WINDOW 条邻居，再语义扩展。

    无条件邻居保证对话上下文完整；语义扩展=锚点{种子, 最近两条已吸收}加权相似度，
    或同人豁免；连续失败停止；向量不可用时语义判定退化为字符相似度（同人豁免保留）。
    """
    n = len(messages)
    cluster = {seed_idx}

    # vecs 按消息 id 索引；idx_to_vec 把位置号映射到向量
    if vecs:
        idx_to_vec = {i: vecs.get(int(messages[i]["id"])) for i in range(n)}
    else:
        idx_to_vec = {}

    # 时间闸：窗口内允许纳入的最大时间间隔
    base_gap = max(1800, (window_times[-1] - window_times[0]) / max(n, 1) * 8)

    # 无条件 ±WINDOW 邻居
    for i in range(max(0, seed_idx - WINDOW), min(n, seed_idx + WINDOW + 1)):
        if i == seed_idx:
            continue
        gap = abs(window_times[i] - window_times[seed_idx])
        if gap <= base_gap:
            cluster.add(i)

    seed_author = messages[seed_idx]["uin"]
    seed_vec = idx_to_vec.get(seed_idx)
    has_vec = seed_vec is not None

    def make_anchors(direction: int) -> list[int]:
        """方向锚点 = {种子, 该方向最近两条已吸收}。direction=1 向后(更晚), -1 向前(更早)。"""
        ans = [seed_idx]
        offsets = [direction, 2 * direction]
        for off in offsets:
            i = seed_idx + off
            if 0 <= i < n and i in cluster:
                ans.append(i)
        return ans

    def anchor_sem_sim(anchors: list[int], idx: int) -> float:
        """与锚点的加权平均相似度（种子 0.6 主导 + 最近两条各 0.2）。"""
        weights = SEM_ANCHOR_WEIGHTS
        total = 0.0
        wsum = 0.0
        for a, w in zip(anchors, weights):
            if idx == a:
                return 1.0
            s = _cosine_sim(idx_to_vec.get(idx), idx_to_vec.get(a))
            total += w * s
            wsum += w
        return total / wsum if wsum else 0.0

    def absorb(anchors: list[int], idx: int):
        cluster.add(idx)
        anchors.append(idx)
        if len(anchors) > 3:
            # 淘汰最老的非种子锚点（保种子在 anchors[0]）
            for a in anchors:
                if a != seed_idx:
                    anchors.remove(a)
                    break

    def same_author_exempt(anchors: list[int], idx: int) -> bool:
        """同人豁免：与种子同人，或候选+锚点中最近两条 3 连同人。"""
        if messages[idx]["uin"] == seed_author:
            return True
        return len(anchors) >= 2 and \
            all(messages[a]["uin"] == messages[idx]["uin"] for a in anchors[1:])

    # 向前扩展（更早方向）
    anchors = make_anchors(-1)
    prev = min(cluster)
    j = prev - 1
    fail = 0
    while j >= 0 and len(cluster) < CLUSTER_MAX:
        gap = window_times[prev] - window_times[j]
        if gap > base_gap:
            break
        if same_author_exempt(anchors, j):
            absorb(anchors, j)
            prev = j
            fail = 0
        else:
            if has_vec:
                accepted = anchor_sem_sim(anchors, j) >= SEM_EXPAND_MIN
            else:
                accepted = _char_sim(messages[prev]["content"], messages[j]["content"]) >= SIM_THRESHOLD
            if accepted:
                absorb(anchors, j)
                prev = j
                fail = 0
            else:
                fail += 1
                if fail >= EXPAND_FAIL_LIMIT:
                    break
        j -= 1

    # 向后扩展（更晚方向）
    anchors = make_anchors(1)
    nxt = max(cluster)
    j = nxt + 1
    fail = 0
    while j < n and len(cluster) < CLUSTER_MAX:
        gap = window_times[j] - window_times[nxt]
        if gap > base_gap:
            break
        if same_author_exempt(anchors, j):
            absorb(anchors, j)
            nxt = j
            fail = 0
        else:
            if has_vec:
                accepted = anchor_sem_sim(anchors, j) >= SEM_EXPAND_MIN
            else:
                accepted = _char_sim(messages[nxt]["content"], messages[j]["content"]) >= SIM_THRESHOLD
            if accepted:
                absorb(anchors, j)
                nxt = j
                fail = 0
            else:
                fail += 1
                if fail >= EXPAND_FAIL_LIMIT:
                    break
        j += 1

    return sorted(cluster)


def extract_clusters(messages: list[dict], seeds: list[int],
                     vecs: dict[int, object] | None = None) -> list[list[int]]:
    """对每个种子扩展集群，合并重叠。vecs 为该群 id→向量的映射。"""
    window_times = [m["time"] for m in messages]
    clusters: list[list[int]] = []
    for idx in seeds:
        cl = _expand_cluster(messages, idx, window_times, vecs)
        if not cl:
            continue
        merged = None
        for i, existing in enumerate(clusters):
            if set(existing) & set(cl):
                merged = i
                break
        if merged is not None:
            clusters[merged] = sorted(set(clusters[merged]) | set(cl))
        else:
            clusters.append(cl)
    return clusters


class ClusterCompressor(BaseDocumentCompressor):
    """对候选窗口做集群提取 → 平均 RRF 分降序 → top-N → token 预算裁剪 → 分组。

    输出顺序即最终上下文顺序：每个集群一组（组内 id 升序），recent 恒保留组追加在后。
    metadata 上会追加 "_block"/"_seq"，格式化步骤据此重建分组文本。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    def __init__(self, docs: Sequence[Document], seeds: list[int],
                 rrf_score: dict[int, float], vec_map) -> None:
        super().__init__()  # 初始化 pydantic 内部（extra="allow" 需要 __pydantic_extra__）
        self.docs = list(docs)
        self.msgs = docs_to_msgs(self.docs)
        self.seeds = seeds
        self.rrf_score = rrf_score
        self.vec_map = vec_map
        self.blocks: list[list[int]] = []   # 供调试：最终进入上下文的块（窗口下标）

    def compress_documents(self, documents: Sequence[Document], query: str = "",
                           callbacks=None) -> list[Document]:
        self.docs = list(documents)
        self.msgs = docs_to_msgs(self.docs)
        self._build_blocks()
        return self._flatten_annotated()

    # ── 选簇 → 裁剪 → 分组 ────────────────────────────────────────────────
    def _build_blocks(self) -> None:
        msgs = self.msgs
        n = len(msgs)
        clusters = extract_clusters(msgs, self.seeds, self.vec_map)

        def cluster_key(cl):
            scores = [self.rrf_score.get(i, 0.0) for i in cl if i in self.rrf_score]
            return sum(scores) / len(scores) if scores else 0.0

        clusters.sort(key=cluster_key, reverse=True)
        selected = list(clusters[: OUTPUT_TOP])

        recent = list(range(max(0, n - RECENT_N), n))
        recent_set = set(recent)

        def _est_tokens(idx_blocks: list[list[int]]) -> int:
            seen: set[int] = set()
            total = 0
            for blk in idx_blocks:
                for i in blk:
                    if i in seen:
                        continue
                    seen.add(i)
                    total += int(len(msgs[i]["content"]) / 1.3 + 7) + len(msgs[i]["name"])
            return total

        kept = list(selected)
        while len(kept) > 1 and _est_tokens(kept + [recent]) > TOKEN_BUDGET:
            kept.pop()

        blocks: list[list[int]] = []
        seen_block_ids: set[int] = set()
        for cl in kept:
            members = sorted(cl)
            blocks.append(members)
            seen_block_ids.update(members)
        recent_only = [i for i in recent if i not in seen_block_ids]
        if recent_only:
            blocks.append(recent_only)
        self.blocks = blocks

    def _flatten_annotated(self) -> list[Document]:
        out: list[Document] = []
        for b, block in enumerate(self.blocks):
            for seq, i in enumerate(block):
                d = self.docs[i]
                out.append(Document(
                    page_content=d.page_content,
                    metadata={**d.metadata, "_block": b, "_seq": seq},
                ))
        return out


def format_context(compressed: Sequence[Document]) -> str:
    """把 compress_documents 输出（带 _block/_seq）还原为分组文本。

    组内按 _seq 顺序换行，组间空行。

    时间戳压缩（省 ~30% 上下文 token）：同一天只在当日首条消息上输出完整日期，
    同日后续行只保留 HH:MM。日期按整段全局追踪（跨块延续），模型仍可据
    "当日首条出现日期" 推出每条属于哪一天。
    """
    parts: list[list[str]] = []
    cur = -1
    last_day: str | None = None
    for d in compressed:
        b = d.metadata["_block"]
        if b != cur:
            parts.append([])
            cur = b
        content = d.page_content[: MAX_RETRIEVE_LEN]
        full = time.strftime("%m-%d %H:%M", time.localtime(d.metadata["time"]))
        day, hhmm = full[:5], full[6:]
        if day == last_day:
            ts = hhmm
        else:
            ts = full
            last_day = day
        parts[-1].append(f"{ts} {d.metadata['name']}: {content}")
    return "\n\n".join("\n".join(block) for block in parts)
