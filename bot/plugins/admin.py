from __future__ import annotations

import asyncio
import json
import httpx

from helper_fun import get_user_nickname
from bot.plugin import Deps, Feature, Matcher, register
from bot.request import Outcome, Reply, Request
from constant import *


async def _lookup_nickname(qq: int) -> str | None:
    """昵称查询失败（非好友、非群成员等）返回 None，由调用方决定降级文案。"""
    nick = await get_user_nickname(qq)
    return None if nick == '未知昵称' else nick


@register
class FeatureAdmin(Feature):
    name = FeatureName.ADMIN
    priority = -1
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.api = deps.api

    async def function(self, req: Request) -> Outcome:
        msg = req.msg.strip()
        qq = req.qq
        admin = req.admin
        super_admin = req.super_admin
        options = req.options

        if qq not in admin and qq != super_admin:
            cmd = msg.split(maxsplit=1)[0]
            if cmd in AdminMap or msg.startswith(
                ('打开 ', '关闭 ', '加入黑名单 ', '移出黑名单 ')
            ) or msg == '清理缓存':
                return Outcome.handled(Reply.same_conversation(req, '权限不足'))
            return Outcome.pass_()

        text = ''
        if qq == super_admin:
            if (msg.startswith('打开 ') or msg.startswith('关闭 ')) and len(msg) > 3:
                value = 1 if msg.startswith('打开 ') else 0
                feature_name = FEATURE_ALIAS_REVERSE.get(msg[3:].strip(), msg[3:].strip())
                if feature_name not in options:
                    text = f'未知的功能名：{feature_name}'
                else:
                    if value == options[feature_name]:
                        text = f'功能{feature_name}已打开/关闭，请勿重复操作'
                    else:
                        text = await self.api.set_option(feature_name, value)
            elif (msg.startswith('加入黑名单 ') or msg.startswith('移出黑名单 ')) and len(msg) > 6:
                oper_qq = msg[6:].strip()
                value = 1 if msg.startswith('加入黑名单 ') else 0
                if oper_qq.isdigit():
                    oper_qq = int(oper_qq)
                    text = await self.api.block_user(oper_qq, value)
                else:
                    text = '错误的指令格式'
            elif msg.startswith('单群打开 ') or msg.startswith('单群关闭 ') or msg.startswith('还原单群 '):
                if msg.startswith('单群打开 '):
                    value = 1
                elif msg.startswith('单群关闭 '):
                    value = 0
                else:
                    value = None
                parts = msg.split(maxsplit=2)
                if len(parts) < 3 or not parts[1].isdigit():
                    text = '指令格式：单群打开/单群关闭/还原单群 <群号> <功能>'
                else:
                    gid = int(parts[1])
                    fname = FEATURE_ALIAS_REVERSE.get(parts[2].strip(), parts[2].strip())
                    if fname not in options:
                        text = f'未知的功能名：{fname}'
                    elif value is None:
                        text = await self.api.group_reset_option(gid, fname)
                    else:
                        text = await self.api.group_set_option(gid, fname, value)
            elif msg == '清理缓存':
                text = await self.api.reset_all()

        if not text:
            parts = msg.split(maxsplit=1)
            cmd: str = parts[0]
            arg: str | None = parts[1] if len(parts) > 1 else None

            if cmd in AdminMap:
                command_config = AdminMap[cmd]
                feature = command_config.feature_name
                action = command_config.cmd_str
                need_args = command_config.need_args
                super_only = command_config.super_only
                if super_only and qq != super_admin:
                    text = '权限不足'
                elif arg is None and need_args:
                    text = '指令不完整，请给出参数'
                else:
                    kwargs = {}
                    if arg:
                        kwargs[Name.ARG] = arg.strip()
                    kwargs[Name.GROUP] = req.group_id
                    text = await self.api.feature_action(feature, action, **kwargs)

        return Outcome.handled(Reply.same_conversation(req, text)) if text else Outcome.pass_()


@register
class FeatureReadOptions(Matcher):
    name = FeatureName.READOPTIONS
    priority = 0
    abstract = False

    @staticmethod
    async def _read_blackpot_num() -> str:
        if not BLACKPOT_API_URL:
            return '未配置暗锅查询服务'
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = BLACKPOT_API_URL
            headers = {'Content-Type': 'application/json'}
            data = json.dumps({'api': "login", 'uid': "robot", 'token': BLACKPOT_TOKEN})

            response = await client.post(url, headers=headers, data=data)
            cookie = response.headers['Set-Cookie']
            data = json.dumps({'api': "getSeasonData"})
            headers = {'Content-Type': 'application/json', 'Cookie': cookie}
            response = await client.post(url, headers=headers, data=data)
            js = response.json()['data']
            text = f"已有{js['user']}人共出{js['question']}题"
            return text

    @staticmethod
    async def _read_bank():
        def _sync():
            with open(JsonPath.COIN, 'r') as f:
                bank = json.load(f)
            return bank
        bank = await asyncio.to_thread(_sync)
        text = DELIMITER
        for i in bank:
            text += bank[i][1] + '(' + i + ')' + ':' + str(bank[i][0]) + '\n'
        return text

    async def match(self, req: Request) -> Reply | None:
        msg = req.msg
        if msg == '查看设置':
            nicks = await asyncio.gather(
                *(_lookup_nickname(i) for i in [*req.admin, *req.blacklist, req.super_admin]))
            admin_names = [n or str(q) for n, q in zip(nicks[:len(req.admin)], req.admin)]
            black_names = [n or str(q) for n, q in
                           zip(nicks[len(req.admin):len(req.admin) + len(req.blacklist)],
                               req.blacklist)]
            super_nick = nicks[-1]
            # 只有超级管理员带 QQ 号；查不到昵称时只留 QQ 号
            super_name = (str(req.super_admin) if super_nick is None
                          else f'{super_nick}({req.super_admin})')
            return Reply.same_conversation(req, "\n".join([
                "已开启功能：" + "、".join(
                    str(FEATURE_ALIAS.get(k, k)) for k, v in req.options.items() if v == 1),
                "管理员：" + "、".join(admin_names),
                "超级管理员：" + super_name,
                "黑名单：" + "、".join(black_names),
            ]))
        if msg == '全部功能':
            return Reply.same_conversation(req, "全部功能：\n" + "、".join(
                f'{FEATURE_ALIAS[k]}({k})' if k in FEATURE_ALIAS else str(k) for k in req.options))
        if msg == '暗锅题数':
            return Reply.same_conversation(req, await self._read_blackpot_num())
        if msg == '查看铸币':
            return Reply.same_conversation(req, await self._read_bank())
        return None
