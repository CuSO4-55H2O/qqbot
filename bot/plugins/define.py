from __future__ import annotations

import asyncio
import time
import re
import sqlite3

from dataclasses import replace
from datetime import datetime
from bot.plugin import Deps, Matcher, register
from bot.request import Outcome, Reply, Request
from bot.cq import _at_to_text, _strip_files, _extract_media, _IMG_PLACEHOLDER, _FILE_TEXT
from constant import *


@register
class FeatureDefine(Matcher):
    name = FeatureName.DEFINE
    priority = 99
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.db_route = DBPath.DEFINE
        self.used: dict[int, dict[str, int]] = {}
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            cursor.execute('''create table if not exists define(
                keyword text primary key,
                content text not null,
                definer_qq integer,
                definer_nickname text,
                create_time integer
            );''')
            # 定义里的图片存这儿：正文只留 [img:N] 占位，字节跟着定义走、不受 URL 过期影响
            cursor.execute('''create table if not exists define_media(
                keyword text not null,
                seq integer not null,
                data text not null,
                primary key (keyword, seq)
            );''')
            conn.commit()

    async def reset_cache(self):
        self.used.clear()

    async def _get_define(self, keyword: str) -> tuple | None:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                cursor.execute('select keyword, content, definer_qq, definer_nickname, create_time from define where keyword=?;', (keyword,))
                return cursor.fetchone()
        return await asyncio.to_thread(_sync)

    async def _all_defines(self) -> list[tuple]:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                cursor.execute('select keyword, content from define;')
                return cursor.fetchall()
        return await asyncio.to_thread(_sync)

    async def _get_media(self, keyword: str) -> list[str]:
        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                rows = conn.execute(
                    'select data from define_media where keyword=? order by seq;',
                    (keyword,)).fetchall()
                return [r[0] for r in rows]
        return await asyncio.to_thread(_sync)

    async def _render(self, keyword: str, content: str) -> str:
        """正文还原成可发送的文本：占位符 → 真图 base64；老数据里的裸文件码 → 文字占位。

        先剥裸码、再填占位，顺序不能反 —— 否则刚填进去的 base64 图会被一起剥掉。
        """
        content = _strip_files(content)
        if not _IMG_PLACEHOLDER.search(content):
            return content
        media = await self._get_media(keyword)

        def sub(m):
            i = int(m.group(1))
            if i < len(media):
                return f'[CQ:image,file=base64://{media[i]}]'
            return _FILE_TEXT['image']

        return _IMG_PLACEHOLDER.sub(sub, content)

    async def _add_define(self, keyword: str, content: str, qq: int, nickname: str,
                          media: list[str] | None = None):
        def _sync():
            # 正文和图片在同一个事务里写，不会出现"定义进去了、图没进去"
            with sqlite3.connect(self.db_route) as conn:
                conn.execute(
                    '''insert or replace into define(keyword, content, definer_qq, definer_nickname, create_time)
                       values (?,?,?,?,?);''',
                    (keyword, content, qq, nickname, int(time.time())))
                conn.execute('delete from define_media where keyword=?;', (keyword,))
                if media:
                    conn.executemany(
                        'insert into define_media(keyword, seq, data) values (?,?,?);',
                        [(keyword, i, b64) for i, b64 in enumerate(media)])
                conn.commit()
        await asyncio.to_thread(_sync)

    async def _delete_own_define(self, keyword: str, qq: int, super_admin: int,
                                 administrators: list[int]) -> str:
        """用户侧删除。权限照抄 `_delete_record`：超管 / 机器人管理员 / 定义者本人。"""
        def _sync():
            # 查归属和删除必须在同一个事务里，否则查完到删之间定义可能被换掉
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                cursor.execute('select definer_qq from define where keyword=?;', (keyword,))
                row = cursor.fetchone()
                if not row:
                    return f'不存在关键词为{keyword}的定义'
                definer = row[0]
                if qq != super_admin and qq not in administrators and qq != definer:
                    return '只能删除自己定义的内容'
                cursor.execute('delete from define where keyword=?;', (keyword,))
                conn.execute('delete from define_media where keyword=?;', (keyword,))
                conn.commit()
                return '已删除'
        return await asyncio.to_thread(_sync)

    async def match(self, req: Request) -> Reply | Outcome | list[Reply] | None:
        msg = req.msg
        group = req.group_id
        if not req.is_group:
            return None
        admin = req.admin
        qq = req.qq

        if msg.startswith("定义") and ("=" in msg or "＝" in msg):
            eq_idx = min([i for i in (msg.find('='), msg.find('＝')) if i != -1])
            keyword = msg[2:eq_idx]
            content = msg[eq_idx + 1:]

            if '[CQ:' in keyword:
                return Reply.same_conversation(req, '关键词不能包含特殊消息')
            if ' ' in keyword or '　' in keyword:
                return Reply.same_conversation(req, '关键词不能包含空格')
            if not keyword:
                return Reply.same_conversation(req, '关键词不能为空')
            if not content:
                return Reply.same_conversation(req, '定义内容不能为空')
            if len(keyword) > 15:
                return Reply.same_conversation(req, '关键词太长了')
            if await self._get_define(keyword) and qq not in admin and qq != req.super_admin:
                return Reply.same_conversation(req, '关键词已被定义')
            if msg[-1] != '喵':
                content, media, failed = await _extract_media(content)
                await self._add_define(keyword, content, qq, req.nickname, media)
                # 回显要还原真图：这里是一条普通消息，不是"查看定义"那种列表
                out = [Reply.same_conversation(req, await self._render(keyword, content) + '喵')]
                if failed:
                    out.append(Reply.same_conversation(
                        req, f'有 {failed} 张图片存不下来（链接已失效或超过 5MB），已换成文字占位'))
                return out
            # 以「喵」结尾的定义不写库，但算接住
            return Outcome.silent()

        if msg == "查看定义":
            rows = await self._all_defines()
            text = ""
            for keyword, content in rows:
                # 列表也还原真图：库里存的是 base64，不需要下载，所以不会像以前那样撞 URL 过期
                text = text + keyword + "=" + await self._render(keyword, _at_to_text(content)) + "\n"
            return Reply.same_conversation(req, text)

        if msg == "查看定义者":
            return Reply.same_conversation(req, '要查哪个关键词？')

        if msg.startswith("查看定义者 "):
            keyword = msg[5:].strip()
            if not keyword:
                return Reply.same_conversation(req, '要查哪个关键词？')
            row = await self._get_define(keyword)
            if not row:
                return Reply.same_conversation(req, f'关键词「{keyword}」未被定义')
            _, content, definer_qq, definer_nickname, create_time = row
            if definer_qq is None or definer_nickname is None or create_time is None:
                return Reply.same_conversation(req, '该关键词没有存储定义者信息')
            time_str = datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M')
            return Reply.same_conversation(
                req, f'关键词【{keyword}】由 {definer_nickname}（{definer_qq}）在 {time_str} 定义')

        # 删除是业务功能（照 record 的「删除记录」），不是管理命令 —— 所以名字不在 AdminMap 里，
        # 普通用户能走到这儿；权限由 _delete_own_define 按归属判。
        if msg.startswith("删除定义 "):
            keyword = msg[len("删除定义 "):].strip()
            if not keyword:
                return Reply.same_conversation(req, '要删哪个关键词？')
            return Reply.same_conversation(
                req, await self._delete_own_define(keyword, qq, req.super_admin, admin))

        clean_msg = re.sub(r'\[.*?]', '', msg).replace(' ', '').replace('　', '')
        row = await self._get_define(clean_msg)
        if row:
            if group not in self.used:
                self.used[group] = {}
            if clean_msg not in self.used[group]:
                self.used[group][clean_msg] = 0
            if time.time() - self.used[group][clean_msg] > 10:
                text = await self._render(clean_msg, row[1])
                self.used[group][clean_msg] = int(time.time())
                return Reply.same_conversation(req, text)
        return None
