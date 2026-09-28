"""检索与聚类的调优常量（单源）。

只被读路径用：retrieve / retrievers / cluster / tools。chat_rag 是写路径 + 存储，
一个都不读。集中在这里，免得像 tools 那样各处再抄一份。

标了「调优」的都是可以试的数 —— 改之前先想清楚它牵动什么。
"""

from __future__ import annotations

import os

# ── 检索：候选窗口 + 双路种子 + RRF ──────────────────────────────────────────

CANDIDATE_HOURS = 720      # 没给时间范围时，往回扫多少小时
CANDIDATE_MAX = 20000      # 一次最多取多少条候选
                           # ⚠ 隐含截断：按当前数据量 2 万条 ≈ 最近 6.7 天，
                           #   群越活跃这个窗口越短，且不报错（所谓"近 30 天"是假的）
SEED_K = 20                # 传统路取前几名当种子
SEM_SEED_K = 20            # 语义路取前几名当种子
SEM_SEED_MIN = float(os.environ.get("RAG_SEM_SEED_MIN", "0.5"))
RRF_K = 25                 # RRF 分母常数，越大越平（名次间差距越小）

# ── 对话集群扩展 ────────────────────────────────────────────────────────────

WINDOW = 2                 # 种子前后各无条件纳入几条邻居
CLUSTER_MAX = 50           # 单个集群最多吞多少条
SEM_EXPAND_MIN = float(os.environ.get("RAG_SEM_EXPAND_MIN", "0.4"))
SIM_THRESHOLD = 0.15       # 兜底门槛：拿不到向量时改用字符相似度判定
EXPAND_FAIL_LIMIT = 3      # 某个方向连续失败几次就停
SEM_ANCHOR_WEIGHTS = (0.6, 0.2, 0.2)   # 权重顺序：种子, 最近已吸收1, 最近已吸收2

# ── 输出裁剪与分组 ──────────────────────────────────────────────────────────

OUTPUT_TOP = 10            # 最多保留几个集群
RECENT_N = 8               # 最近这几条恒定保留（不管有没有被检索命中）
TOKEN_BUDGET = 8000        # 上下文的估算 token 预算，超了从尾部集群丢
MAX_RETRIEVE_LEN = 200     # 单条消息进入上下文时的截断长度
