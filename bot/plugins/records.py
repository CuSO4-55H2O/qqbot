from __future__ import annotations

import asyncio
import time
import re
import random
import sqlite3

from helper_fun import get_message
from bot.plugin import Deps, Feature, register
from bot.request import Forward, Outcome, Outbound, Reply, Request
from constant import *


@register
class FeatureRecord(Feature):
    name = FeatureName.RECORD
    priority = 2
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.db_route = DBPath.RECORD
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS record (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    uin INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    time REAL NOT NULL,
                    num INTEGER NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                )
            ''')
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_record_group ON record(group_id, archived)')
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_record_uin ON record(group_id, uin)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS record_counter (
                    group_id INTEGER PRIMARY KEY,
                    next_num INTEGER NOT NULL DEFAULT 1
                )
            ''')
            conn.commit()

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_cq_at(text: str) -> dict:
        """匹配 [CQ:at,qq=数字,name=...] 提取 qq"""
        pattern = r'\[CQ:at,qq=(\d+),name=(.*?)\]'
        match = re.match(pattern, text)
        if match:
            return {'matched': True, 'qq': match.group(1)}
        return {'matched': False}

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def _record(self, mes: dict, group: int) -> str:
        """插入一条记录，返回状态文本"""
        if 'https://multimedia.nt.qq.com.cn' in mes['content']:
            return '该记录不符合要求'
        pattern = r'\[CQ:(?:at,qq=\d+,name=[^\]]+|reply,id=\d+)\]'
        content = re.sub(pattern, '', mes['content'])

        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO record_counter (group_id, next_num) VALUES (?, 1) '
                    'ON CONFLICT(group_id) DO UPDATE SET next_num = next_num + 1 '
                    'RETURNING next_num',
                    (group,))
                num = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO record (group_id, uin, name, content, time, num) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (group, mes['uin'], mes['name'], content, mes['time'], num))
                conn.commit()
        await asyncio.to_thread(_sync)
        return '已记录'

    async def _record_id(self, msg_id: int, blacklist: list[int]) -> str:
        """通过回复消息 ID 记录"""
        rev = await get_message(msg_id)
        group = rev['group_id']
        qq = int(rev['sender']['user_id'])
        mes = rev['message']
        nickname = rev['sender']['nickname']
        t = rev['time']
        i = {'name': nickname, 'uin': qq, 'content': mes, 'time': t}
        if qq not in blacklist:
            return await self._record(i, group)
        return ''

    async def _delete_record(self, num: str, group: int, qq: int,
                             super_admin: int, administrators: list[int]) -> str:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT uin FROM record WHERE group_id = ? AND num = ? AND archived = 0',
                    (group, num))
                row = cursor.fetchone()
                if not row:
                    return '不包含对应编号的记录'
                uin = row[0]
                if qq != super_admin and qq not in administrators and qq != uin:
                    return '只能删除自己的记录'
                cursor.execute(
                    'DELETE FROM record WHERE group_id = ? AND num = ? AND archived = 0',
                    (group, num))
                conn.commit()
                return '已删除'
        return await asyncio.to_thread(_sync)

    async def _read_record(self, group: int, mode: RecordMode, qq_arg) -> list[Outbound]:
        """读取/展示记录。VIEW=格式化 RAW=原始forward SEARCH=按QQ搜 ARCHIVED=归档

        只构建「要发什么」，发送交给 BotCore —— 连发时的节流（gap）作为返回值
        的一部分带出去，因为节奏是发送的属性，不是这条记录数据的属性。
        """
        search_qq = 0
        if mode == RecordMode.SEARCH:
            i = self._extract_cq_at(str(qq_arg))
            search_qq = int(i['qq']) if i['matched'] else int(qq_arg)

        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                conn.row_factory = sqlite3.Row
                if mode == RecordMode.ARCHIVED:
                    rows = conn.execute(
                        'SELECT * FROM record WHERE group_id = ? AND archived = 1 '
                        'ORDER BY num', (group,)).fetchall()
                elif mode == RecordMode.SEARCH:
                    rows = conn.execute(
                        'SELECT * FROM record WHERE group_id = ? AND uin = ? '
                        'ORDER BY num', (group, search_qq)).fetchall()
                else:
                    rows = conn.execute(
                        'SELECT * FROM record WHERE group_id = ? AND archived = 0 '
                        'ORDER BY num', (group,)).fetchall()
                return [dict(r) for r in rows]

        records = await asyncio.to_thread(_sync)

        if not records:
            return [Reply(msg='本群还没有记录过', msg_type=Name.GROUP, number=group)]

        # ── 分离记录类型 ──
        normal_rows = [r for r in records if '[CQ:forward' not in r['content']]
        forward_rows = [r for r in records if '[CQ:forward' in r['content']]

        # RAW 模式：逐条发送 forward 消息原文
        if mode == RecordMode.RAW:
            return [Reply(msg=r['content'], msg_type=Name.GROUP, number=group,
                          gap=random.uniform(0.5, 2)) for r in forward_rows]

        # VIEW / SEARCH / ARCHIVED 模式：构建转发合并消息
        if not normal_rows:
            if mode == RecordMode.SEARCH:
                return [Reply(msg='qq号错误/未查询到此人记录',
                              msg_type=Name.GROUP, number=group)]
            return []

        # QQ 合并转发单次最多 100 条，攒满一批就是一条独立的合并转发
        _BATCH_MAX = 100
        out: list[Outbound] = []
        for start in range(0, len(normal_rows), _BATCH_MAX):
            nodes = tuple({
                'type': 'node',
                'data': {
                    'name': f"#{r['num']}{r['name']}",
                    'uin': r['uin'],
                    'content': r['content'],
                    'time': r['time'],
                },
            } for r in normal_rows[start:start + _BATCH_MAX])
            out.append(Forward(nodes=nodes, number=group, gap=random.uniform(0.5, 2)))
        return out

    # ── 管理功能 ─────────────────────────────────────────────────────────

    async def _archive_records(self, group: str) -> str:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT COUNT(*) FROM record WHERE group_id = ? AND archived = 0',
                    (group,))
                count = cursor.fetchone()[0]
                if count == 0:
                    return '当前没有可归档的记录'
                cursor.execute(
                    'UPDATE record SET archived = 1 '
                    'WHERE group_id = ? AND archived = 0', (group,))
                conn.commit()
                return f'已归档 {count} 条记录'
        return await asyncio.to_thread(_sync)

    async def admin_action(self, action: str, **kwargs) -> str:
        if action == AdminCMD.ARCHIVE_RECORD:
            group = kwargs[Name.GROUP]
            if group:
                return await self._archive_records(str(group))
            else:
                return '该管理功能只能在群聊中使用'
        else:
            return '未知的管理指令'

    # ── 入口 ─────────────────────────────────────────────────────────────

    async def function(self, req: Request) -> Outcome:
        if not req.is_group:
            return Outcome.pass_()
        msg, group = req.msg, req.group_id
        text = ''

        if msg.startswith('记录 '):
            i = {'name': req.nickname, 'uin': req.qq, 'content': msg[3:],
                 'time': time.time()}
            text = await self._record(i, group)
        elif len(msg) > 5 and msg.startswith('删除记录 '):
            text = await self._delete_record(msg[5:], group, req.qq,
                                             req.super_admin, req.admin)
        elif '[CQ:reply' in msg:
            m = re.sub(r'\[.*?]', '', msg).replace(' ', '')
            if m != '记录':
                return Outcome.pass_()
            msg_id = re.search(r'CQ:reply,id=(\d+)', msg).group(1)
            text = await self._record_id(msg_id, req.blacklist)
        elif msg == '查看记录':
            return Outcome.handled(*await self._read_record(group, RecordMode.VIEW, 0))
        elif msg == '记录查看':
            return Outcome.handled(*await self._read_record(group, RecordMode.RAW, 0))
        elif msg == '查看历史记录':
            return Outcome.handled(*await self._read_record(group, RecordMode.ARCHIVED, 0))
        elif len(msg) > 4 and msg.startswith('查看记录'):
            return Outcome.handled(
                *await self._read_record(group, RecordMode.SEARCH, msg[4:]))
        else:
            return Outcome.pass_()

        # 上面几条读命令返回自己的 outbound；这里只处理会攒出 text 的分支。
        # text 为空表示接住但无话可说。
        return Outcome.handled(Reply.same_conversation(req, text)) if text else Outcome.silent()
