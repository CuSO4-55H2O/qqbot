"""roulette 对局记录：SQLite 存储（替代原 MySQL）

单文件 SQLite，轻量、无独立服务，随程序同目录持久化。
写入用同步 sqlite3，量小（一场对局几十行），外层套 asyncio.to_thread 不阻塞事件循环。
三个函数均返回 (match_id, players_dict)，结构见函数注释。
"""

import asyncio
import sqlite3
import time

from constant import DBPath

DB_ROUTE = DBPath.ROULETTE

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS match (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   INTEGER NOT NULL,
    start_time REAL    NOT NULL,
    end_time   REAL,
    mode_flags TEXT    NOT NULL,
    winner_id  INTEGER
);
CREATE TABLE IF NOT EXISTS match_player (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    seat_index  INTEGER NOT NULL,
    coin_change REAL    NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS match_event (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    turn_num INTEGER NOT NULL,
    content  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_match_player_match ON match_player(match_id);
CREATE INDEX IF NOT EXISTS idx_match_event_match ON match_event(match_id);
'''


def init_db():
    """初始化表结构（幂等）。"""
    with sqlite3.connect(DB_ROUTE) as conn:
        conn.executescript(_SCHEMA)


def _create_match_sync(group_id: int, mode_ids: list) -> int:
    """创建对局，返回新 match 的 id。"""
    mode_flags = mode_ids if isinstance(mode_ids, str) else \
        __import__('json').dumps(mode_ids, ensure_ascii=False)
    with sqlite3.connect(DB_ROUTE) as conn:
        cur = conn.execute(
            'INSERT INTO match (group_id, start_time, mode_flags) VALUES (?,?,?)',
            (group_id, time.time(), mode_flags))
        return cur.lastrowid


async def create_match(group_id: int, mode_ids: list) -> int:
    """创建对局记录，返回 match id。"""
    return await asyncio.to_thread(_create_match_sync, group_id, mode_ids)


def _add_players_sync(match_id: int, players: list):
    """写入两名玩家，players 为 [(user_id, seat_index), ...]"""
    with sqlite3.connect(DB_ROUTE) as conn:
        conn.executemany(
            'INSERT INTO match_player (match_id, user_id, seat_index) VALUES (?,?,?)',
            [(match_id, uid, seat) for uid, seat in players])


async def add_players(match_id: int, players: list):
    """写入两名玩家。players: [(user_id, seat_index), ...]"""
    await asyncio.to_thread(_add_players_sync, match_id, players)


def _add_event_sync(match_id: int, turn_num: int, content: str):
    with sqlite3.connect(DB_ROUTE) as conn:
        conn.execute(
            'INSERT INTO match_event (match_id, turn_num, content) VALUES (?,?,?)',
            (match_id, turn_num, content))


async def add_event(match_id: int, turn_num: int, content: str):
    """记录一回合操作内容。失败由调用方兜底（不阻断游戏）。"""
    await asyncio.to_thread(_add_event_sync, match_id, turn_num, content)


def _finish_match_sync(match_id: int, winner_id, scores: dict):
    """结算对局：写 winner、end_time，并更新每名玩家的 coin_change。scores: {seat_index: coin_change}"""
    with sqlite3.connect(DB_ROUTE) as conn:
        conn.execute(
            'UPDATE match SET end_time=?, winner_id=? WHERE id=?',
            (time.time(), winner_id, match_id))
        for seat, coin in scores.items():
            conn.execute(
                'UPDATE match_player SET coin_change=? WHERE match_id=? AND seat_index=?',
                (coin, match_id, seat))


async def finish_match(match_id: int, winner_id, scores: dict):
    """结算对局：写 winner/end_time，更新玩家 coin_change。"""
    await asyncio.to_thread(_finish_match_sync, match_id, winner_id, scores)


def _get_match_sync(match_id: int):
    with sqlite3.connect(DB_ROUTE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT id, group_id, start_time, end_time, mode_flags, winner_id '
            'FROM match WHERE id=?', (match_id,)).fetchone()
        return dict(row) if row else None


async def get_match(match_id: int):
    """查询对局信息，无则返回 None。"""
    return await asyncio.to_thread(_get_match_sync, match_id)


def _list_events_sync(match_id: int) -> list:
    with sqlite3.connect(DB_ROUTE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT turn_num, content FROM match_event '
            'WHERE match_id=? ORDER BY id', (match_id,)).fetchall()
        return [dict(r) for r in rows]


async def list_events(match_id: int) -> list:
    """按发生顺序返回该对局的所有回合事件。"""
    return await asyncio.to_thread(_list_events_sync, match_id)
