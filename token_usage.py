"""DeepSeek 调用限额：token 统计 + 加权 + 每日配额

权重（用户确认）：
- 所有功能（%% 联网搜索、% 普通对话、* 单点 RAG 的改写与回答、** 聚合 agent）：输入 ×1、输出 ×3
限额：每用户近 24 小时累计加权 token >= DAILY_LIMIT 拒绝调用；管理员/超级管理员豁免。
token 统计用 deepseek_v4_tokenizer 的 tokenizer.json（tokenizers 库直接加载）。

记录内容（每行 = 一次成功调用，也是调用日志）：
    qq / weighted_token / time / source（功能名）/ query（原始问题，截断）/ in_tokens / out_tokens
source、query、in_tokens、out_tokens 是后加的列：旧库由 init_db 原地补列，旧行这几列为 NULL。
读侧（check_quota）只碰 qq/weighted_token/time，因此补列对旧数据无影响。
"""

import asyncio
import os
import sqlite3
import time
from tokenizers import Tokenizer

from constant import DBPath

DB_ROUTE = DBPath.TOKEN_USAGE
DAILY_LIMIT = 30000
# 一次联网搜索折算成多少加权 token。博查是**按次**计费（资源包），不是按 token，
# 所以只能折一个固定值进来。真实成本约 32000/次，这里定 3000 —— 这个数的作用是
# **限流闸门**，不是成本回收（用户不付费，限额只为防滥用）。
SEARCH_BONUS = 3000
QUERY_MAX = 200          # query 入库截断长度（防长文撑库）

# 后加的可选列：init_db 据此给旧库补列（列名与 DDL 均为常量，不来自外部输入）
_ADDED_COLUMNS = (
    ('source', 'TEXT'),          # 功能名：chat / search / rag / rewrite / agent
    ('query', 'TEXT'),           # 用户原始问题（截断到 QUERY_MAX）
    ('in_tokens', 'INTEGER'),    # 服务端精确输入 token
    ('out_tokens', 'INTEGER'),   # 服务端精确输出 token
)
TOKENIZER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'deepseek_v4_tokenizer', 'tokenizer.json')

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
    return _tokenizer


def count_tokens(text: str) -> int:
    """用 DeepSeek tokenizer 统计文本 token 数。"""
    if not text:
        return 0
    return len(_get_tokenizer().encode(text).ids)


def _connect():
    conn = sqlite3.connect(DB_ROUTE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表 + 补列（幂等）。新库直接建全，旧库缺哪列补哪列。"""
    with _connect() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS token_usage (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                qq             INTEGER NOT NULL,
                weighted_token INTEGER NOT NULL,
                time           REAL    NOT NULL,
                source         TEXT,
                query          TEXT,
                in_tokens      INTEGER,
                out_tokens     INTEGER
            )
        ''')
        # 旧库只有前 4 列。CREATE TABLE IF NOT EXISTS 对已存在的表不做任何事，
        # 所以必须显式补列，否则新写的 INSERT 会因"无此列"整条失败。
        have = {row[1] for row in conn.execute('PRAGMA table_info(token_usage)')}
        for name, decl in _ADDED_COLUMNS:
            if name not in have:
                conn.execute(f'ALTER TABLE token_usage ADD COLUMN {name} {decl}')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_usage_qq_time ON token_usage(qq, time)')


def _usage_sync(qq: int, since: float) -> int:
    with _connect() as conn:
        row = conn.execute(
            'SELECT COALESCE(SUM(weighted_token), 0) FROM token_usage WHERE qq=? AND time>?',
            (qq, since)).fetchone()
        return int(row[0])


def _record_sync(qq: int, weighted: int, source: str | None,
                 query: str | None, inp: int, out: int):
    with _connect() as conn:
        conn.execute(
            'INSERT INTO token_usage '
            '(qq, weighted_token, time, source, query, in_tokens, out_tokens) '
            'VALUES (?,?,?,?,?,?,?)',
            (qq, weighted, time.time(), source,
             (query or '')[:QUERY_MAX] or None, inp, out))


async def check_quota(qq: int, admin, super_admin) -> bool:
    """是否允许调用。达到限额返回 False；管理员/超级管理员永远 True。"""
    if qq in admin or qq == super_admin:
        return True
    used = await asyncio.to_thread(_usage_sync, qq, time.time() - 86400)
    return used < DAILY_LIMIT


async def add_usage(qq: int, input_tokens: int, output_tokens: int,
                    in_weight: int, out_weight: int, *,
                    source: str | None = None, query: str | None = None,
                    bonus_weighted: int = 0):
    """记录一次调用的加权 token 消耗。

    source（功能名）与 query（原始问题）可选，只影响日志可读性，不参与限额判断。

    bonus_weighted 是**不按 token 计的固定加权**（目前只有联网搜索：博查按次收费，
    一次折 SEARCH_BONUS 个加权 token）。单列一个参数是为了不污染 in/out 两列 ——
    那两个数要如实反映 token 用量，塞进去的话日志里就会显示"输入 3000 token"这种假数。
    """
    weighted = input_tokens * in_weight + output_tokens * out_weight + bonus_weighted
    if weighted > 0:
        await asyncio.to_thread(_record_sync, qq, weighted, source, query,
                                input_tokens, output_tokens)
