from __future__ import annotations

import asyncio
import re
import sqlite3

from bot.plugin import Deps, Matcher, register
from bot.request import Reply, Request
from constant import *


@register
class FeatureBottleMail(Matcher):
    name = FeatureName.BOTTLE_MAIL
    priority = 9
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.db_route = DBPath.BOTTLE_MAIL
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql = '''create table if not exists bottle_mail(
            id integer PRIMARY KEY AUTOINCREMENT,
            content text NOT NULL,
            create_time timestamp default current_timestamp
                   );
            '''
            cursor.execute(sql)
            sql = '''create table if not exists hold_bottle(
            user_id integer primary key,
            content text NOT NULL);
            '''
            cursor.execute(sql)

    async def _add_bottle(self, content):
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''insert into bottle_mail(content) values (?);'''
                cursor.execute(sql, (content,))
                conn.commit()
        await asyncio.to_thread(_sync)

    async def _fetch_bottle(self) -> str | None:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''select id,content from bottle_mail order by random() limit 1;'''
                cursor.execute(sql)
                row = cursor.fetchone()
                if not row:
                    return None
                bottle_id, content = row
                sql = '''delete from bottle_mail where id=?;'''
                cursor.execute(sql, (bottle_id,))
                conn.commit()
                return content
        return await asyncio.to_thread(_sync)

    async def _get_hold(self, user_id) -> str | None:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''select content from hold_bottle where user_id = ?;'''
                cursor.execute(sql, (user_id,))
                content = cursor.fetchone()
                return content[0] if content else None
        return await asyncio.to_thread(_sync)

    async def _set_hold(self, user_id: int, content: str):
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''replace into hold_bottle(user_id, content) VALUES (?, ?);'''
                cursor.execute(sql, (user_id, content))
                conn.commit()
        await asyncio.to_thread(_sync)

    async def _delete_hold(self, user_id: int) -> bool:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''DELETE FROM hold_bottle WHERE user_id = ?;'''
                cursor.execute(sql, (user_id,))
                conn.commit()
                return cursor.rowcount > 0
        return await asyncio.to_thread(_sync)

    async def _return_bottle(self, user_id: int):
        def _sync():
            content = None
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''select content from hold_bottle where user_id = ?;'''
                cursor.execute(sql, (user_id,))
                row = cursor.fetchone()
                if row:
                    content = row[0]
            if not content:
                return False
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''INSERT INTO bottle_mail (content) VALUES (?);'''
                cursor.execute(sql, (content,))
                sql = '''delete from hold_bottle where user_id = ?;'''
                cursor.execute(sql, (user_id,))
                conn.commit()
                return True
        return await asyncio.to_thread(_sync)

    async def _count_bottle(self) -> int:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = '''select count(*) from bottle_mail;'''
                cursor.execute(sql)
                row = cursor.fetchone()
                if not row:
                    return 0
                else:
                    return row[0]
        return await asyncio.to_thread(_sync)

    async def match(self, req: Request) -> Reply | None:
        msg, qq = req.msg, req.qq

        if msg.startswith('丢漂流瓶 '):
            if len(msg) >= 6:
                await self._add_bottle(msg[5:])
                return Reply.same_conversation(req, '已丢入漂流瓶海')
            return Reply.same_conversation(req, '要丢什么呢？')

        if msg == '捞漂流瓶':
            hold = await self._get_hold(qq)
            if hold:
                return Reply.same_conversation(
                    req, f'你还有一个未处理的漂流瓶，内容是\n{hold}\n请选择扔漂流瓶或砸漂流瓶')
            bottle = await self._fetch_bottle()
            if bottle:
                await self._set_hold(qq, bottle)
                return Reply.same_conversation(req, f'你捞到了一个漂流瓶，内容是：\n{bottle}')
            return Reply.same_conversation(req, '漂流瓶海里已经没有漂流瓶了')

        if msg == '砸漂流瓶':
            ok = await self._delete_hold(qq)
            return Reply.same_conversation(req, '漂流瓶已经被砸掉' if ok else '你还没有捞漂流瓶')

        if msg == '扔漂流瓶':
            ok = await self._return_bottle(qq)
            return Reply.same_conversation(req, '漂流瓶已经被扔回漂流瓶海' if ok else '你还没有捞漂流瓶')

        if msg == '漂流瓶海':
            return Reply.same_conversation(req, f'漂流瓶海里有{await self._count_bottle()}个漂流瓶')

        return None


@register
class FeatureQueryMiaoKa(Matcher):
    name = FeatureName.QUERY_MIAOKA
    abstract = False
    priority = 12

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.db_route = DBPath.MIAOKA

    async def query_by_se(self, season: int, episode: int) -> str:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                conn.row_factory = sqlite3.Row
                result = conn.execute(
                    """SELECT season, episode, title, post_url, requirement, pub_date
                       FROM miaoka_contest WHERE season = ? AND episode = ?""",
                    (season, episode)
                ).fetchone()
            if result is None:
                return '没有查询到对应的喵赛。'
            result = dict(result)
            text = (f"喵卡周赛 第{result['season']}季 第{result['episode']}期"
                    f"\n标题: {result['title']}\n链接: {result['post_url']}\n"
                    f"发布日期: {result.get('pub_date', '未知')}\n"
                    f"本期要求:\n{result['requirement'] or '(未提取到)'}")
            return text
        return await asyncio.to_thread(_sync)

    async def query_random(self) -> str:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                conn.row_factory = sqlite3.Row
                result = conn.execute(
                    """SELECT season, episode, title, post_url, requirement, pub_date
                       FROM miaoka_contest order by random() limit 1""",
                ).fetchone()
            result = dict(result)
            text = (f"喵卡周赛 第{result['season']}季 第{result['episode']}期"
                    f"\n标题: {result['title']}\n链接: {result['post_url']}\n"
                    f"发布日期: {result.get('pub_date', '未知')}\n"
                    f"本期要求:\n{result['requirement'] or '(未提取到)'}")
            return text
        return await asyncio.to_thread(_sync)

    async def match(self, req: Request) -> Reply | None:
        pattern = re.compile(r'^查询喵赛 (\d+) (\d+)$')
        match = pattern.match(req.msg)
        if match:
            text = await self.query_by_se(int(match.group(1)), int(match.group(2)))
            return Reply.same_conversation(req, text)
        if req.msg == '随机喵赛':
            return Reply.same_conversation(req, await self.query_random())
        return None
