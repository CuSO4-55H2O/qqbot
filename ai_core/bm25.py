"""分词 + BM25 + 多因子打分原语（排序敏感，改动须谨慎）。

单源：检索算法只在本包有一份，chat_rag 的写路径/存储不含打分逻辑。
调优常量在 ai_core/config.py。
"""

from __future__ import annotations

import math
import re

_STOP_CHARS = '的了是在有我没你他她它也都还会就可吧呢吗啊哦嗯哈呀哇'
_BIGRAM_CHAR = re.compile(r'[一-鿿a-zA-Z0-9]')


def tokenize(text: str) -> list[str]:
    """unigram + bigram 混合分词。unigram 过滤停用字，bigram 全部保留。

    例：「A吃了什么」→ ['A','吃','什','么','A吃','吃了','了什','什么']
    """
    chars = _BIGRAM_CHAR.findall(text)
    toks: list[str] = []
    for c in chars:
        if c not in _STOP_CHARS:
            toks.append(c)
    for i in range(len(chars) - 1):
        toks.append(chars[i] + chars[i + 1])
    return toks


class BM25:
    """轻量 BM25，基于 unigram+bigram 分词。"""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.doc_tokens = [tokenize(d) for d in docs]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avg_len = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.N = len(docs)
        self.k1 = k1
        self.b = b
        df: dict[str, int] = {}
        for tokens in self.doc_tokens:
            for tok in set(tokens):
                df[tok] = df.get(tok, 0) + 1
        self.df = df

    def idf(self, tok: str) -> float:
        df = self.df.get(tok, 0)
        if len(tok) == 1:
            return 0.5 * math.log((self.N - df + 0.5) / (df + 0.5) + 1)
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)

    def score_doc(self, doc_idx: int, query_tokens: list[str]) -> float:
        toks = self.doc_tokens[doc_idx]
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        dl = self.doc_len[doc_idx]
        for qt in set(query_tokens):
            f = tf.get(qt, 0)
            if f == 0:
                continue
            idf = self.idf(qt)
            denom = f + self.k1 * (1 - self.b + self.b * dl / max(self.avg_len, 1))
            score += idf * f * (self.k1 + 1) / denom
        return score


def detect_target_names(query: str, names: list[str]) -> set[str]:
    """检测 query 中出现的说话人昵称（长度≥2），命中的人打分提权。"""
    targets: set[str] = set()
    for name in names:
        if len(name) >= 2 and name in query:
            targets.add(name)
    return targets


def _extract_entities(query: str) -> set[str]:
    """问题中的实体：2-3 字的中文片段 + 1-2 字符的字母/数字昵称。"""
    entities: set[str] = set()
    for m in re.finditer(r'[一-鿿]{2,3}', query):
        entities.add(m.group(0))
    for m in re.finditer(r'[a-zA-Z0-9]{1,2}', query):
        entities.add(m.group(0))
    return entities


def score_message(msg: str, bm25: BM25, doc_idx: int, query_tokens: list[str],
                  query: str, now: float, target_names: set[str], msg_name: str) -> float:
    """传统路多因子加权分数：w1 BM25 + w3 实体命中 + w4 说话人提权，长度惩罚。"""
    w1 = bm25.score_doc(doc_idx, query_tokens)

    w3 = 0.0
    for ent in _extract_entities(query):
        if ent in msg:
            w3 += 1.5

    w4 = 1.0 if msg_name in target_names else 0.0

    w1 = w1 / (1 + len(msg) / 200)

    return w1 + w3 + w4
