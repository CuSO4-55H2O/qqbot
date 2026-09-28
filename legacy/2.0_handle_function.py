import os
import json
import time
import re
import random
import requests
import sqlite3
from simpleeval import SimpleEval
from typing import cast

from helper_fun import read_id,get_user_nickname
from output import send_msg,group_poke,recall
import record
import deepseek
import roulette.roulette
import rabble
from constant import *


def read_json( filename: str):
    with open(filename, 'r') as f:
        return json.load(f)

class AdminAPI:
    def __init__(self, set_option, appoint_admin, block_user, feature_action, reset_all):
        self.set_option = set_option
        self.appoint_admin = appoint_admin
        self.block_user = block_user
        self.reset_all = reset_all
        self.feature_action = feature_action

class Plugin:
    name: str = None
    priority: int = 100
    plugin_type: str = ''
    abstract:bool = True

    def is_enabled(self, options: dict) -> bool:
        return options.get(self.name, 0) == 1
    def reset_cache(self):
        """Clear in-memory state. Override in Features that hold caches."""
        pass

class EventHandler(Plugin):
    plugin_type = PluginName.EVENT_HANDLER
    abstract = True
    def handle_event(self, event: dict,ctx:MiniContext) -> bool:
        raise NotImplementedError

class EventHandlerPoke(EventHandler):
    name = EventHandlerName.POKE
    priority = 1
    abstract = False
    def handle_event(self, event: dict,ctx:MiniContext) -> bool:
        if event['post_type']=='notice':
            if event['notice_type'] == 'notify':
                if event['sub_type'] == 'poke' and event['target_id'] == ctx.own_id and 'group_id' in event:
                    group = event['group_id']
                    qq = int(event['user_id'])
                    group_poke(qq, group)
                    return True
        return False

class EventHandlerRevoke(EventHandler):
    name = EventHandlerName.REVOKE
    priority = 2
    abstract = False
    def handle_event(self, event: dict,ctx:MiniContext) -> bool:
        if event['post_type'] == 'notice':
            if event['notice_type'] == 'group_recall':
                recall(event['group_id'], event['message_id'],event['user_id'])
                return True
        return False

class EventHandlerGroupDecrease(EventHandler):
    name = EventHandlerName.GROUP_DECREASE
    priority = 3
    abstract = False
    def handle_event(self, event: dict,ctx:MiniContext) -> bool:
        if event['post_type'] == 'notice':
            if event['notice_type'] == 'group_decrease':
                sub_type = event.get('sub_type')
                user_id = event['user_id']
                group = event['group_id']
                user_nick = get_user_nickname(user_id)  # 假设返回昵称字符串
                if sub_type == 'leave':
                    text = f"{user_nick}({user_id}) 主动退群了"
                elif sub_type == 'kick':
                    operator_id = event.get('operator_id', user_id)  # 踢人者QQ号
                    # 获取踢人者的昵称（若 operator_id 无效则显示“管理员”）
                    if operator_id and operator_id != 0:
                        operator_nick = get_user_nickname(operator_id)
                    else:
                        operator_nick = "管理员"
                    text = f"{user_nick}({user_id}) 被 {operator_nick}({operator_id}) 踢出了群聊"
                else:
                    text = f"{user_nick}({user_id}) 退群了（原因：{sub_type}）"

                send_msg({'msg_type': Name.GROUP, 'number': group, 'msg': text})
        return False

class Feature(Plugin):
    plugin_type =PluginName.FEATURE
    abstract = True

    def function(self,ctx:Context)->Context:
        pass

    @staticmethod
    def reply(ctx:Context, text: str):
        """根据上下文自动添加回复（群聊回复群，私聊回复私聊）"""
        if not ctx.flag or not text:
            return
        msg_type = ctx.msg_type
        if msg_type == Name.GROUP:
            target = ctx.group_id
        else:  # private
            target = ctx.qq
        ctx.send_msg.append({
            'msg_type': msg_type,
            'number': target,
            'msg': text
        })

    def admin_action(self,action:str,**kwargs)->str:
        return '该功能没有对应的管理功能'

class FeatureAdmin(Feature):
    name = FeatureName.ADMIN
    priority = -1
    abstract = False

    def __init__(self, api:AdminAPI):
        self.api = api

    def function(self,ctx:Context)->Context:
        msg=ctx.msg.strip()
        qq=ctx.qq
        admin=ctx.admin
        super_admin=ctx.super_admin
        options:dict[str,int]=ctx.options

        if qq not in admin and qq != super_admin:
            return ctx

        text=''
        if qq ==super_admin:
            if (msg.startswith('打开 ') or msg.startswith('关闭 ') )and len(msg)>3:
                value= 1 if msg.startswith('打开 ') else 0
                feature_name = msg[3:].strip()
                if feature_name not in options:
                    text=f'未知的功能名：{feature_name}'
                else:
                    if value==options[feature_name]:
                        text=f'功能{feature_name}已打开/关闭，请勿重复操作'
                    else:
                        text=self.api.set_option(feature_name,value)
            elif (msg.startswith('加入黑名单 ') or msg.startswith('移出黑名单 ')) and len(msg)>6:
                oper_qq=msg[6:].strip()
                value= 1 if msg.startswith('加入黑名单 ') else 0
                if oper_qq.isdigit():
                    oper_qq=int(oper_qq)
                    text=self.api.block_user(oper_qq,value)
                else:
                    text='错误的指令格式'
            elif msg=='清理缓存':
                text = self.api.reset_all()

        if not text:
            parts = msg.split(maxsplit=1)
            cmd:str = parts[0]  # 指令名
            arg:str|None = parts[1] if len(parts) > 1 else None

            if cmd in AdminMap:
                command_config=AdminMap[cmd]
                feature=command_config.feature_name
                action=command_config.cmd_str
                need_args=command_config.need_args
                super_only=command_config.super_only
                if super_only and qq!=super_admin:
                    text='权限不足'
                elif arg is None and need_args:
                    text='指令不完整，请给出参数'
                else:
                    kwargs = {}
                    if arg:
                        kwargs[Name.ARG] = arg.strip()  # 统一用 key='arg' 传递原始字符串
                    kwargs[Name.GROUP]=ctx.group_id
                    text= self.api.feature_action(feature, action, **kwargs)
        if text:
            ctx.flag=True
        self.reply(ctx, text)
        return ctx

class FeatureReadOptions(Feature):
    name = FeatureName.READOPTIONS
    priority = 0
    abstract = False

    @staticmethod
    def _read_blackpot_num():
        url = 'http://203.0.113.1/node/yaminabe'
        headers = {
            'Content-Type': 'application/json',
        }
        data = json.dumps({
            'api': "login",
            'uid': "robot",
            'token': "123456"
        }
        )

        response = requests.request("POST", url, headers=headers, data=data)
        cookie = response.headers['Set-Cookie']
        data = json.dumps({
            'api': "getSeasonData"
        }
        )
        headers = {
            'Content-Type': 'application/json',
            'Cookie': cookie
        }
        response = requests.request("POST", url, headers=headers, data=data)
        js = response.json()['data']
        text = f"已有{js['user']}人共出{js['question']}题"
        return text

    @staticmethod
    def _read_bank():
        with open('../json/铸币.json', 'r') as f:
            bank = json.load(f)
        text = DELIMITER
        for i in bank:
            text += bank[i][1] + '(' + i + ')' + ':' + str(bank[i][0]) + '\n'
        return text

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg
        admin: list[int] = ctx.admin
        super_admin: int = ctx.super_admin
        blacklist:list[int]=ctx.blacklist
        options:dict[str,int]=ctx.options

        text=''
        if msg=='查看设置':
            text = (
                    "设置：\n" +
                    "\n".join(f"{k}={v}" for k, v in options.items()) + "\n" +
                    "管理员：\n" +
                    "\n".join(str(i) for i in admin) + "\n" +
                    "超级管理员：\n" + str(super_admin) + "\n" +
                    "黑名单：\n" +
                    "\n".join(str(i) for i in blacklist)
            )
            ctx.flag=True
        elif msg=='暗锅题数':
            text=self._read_blackpot_num()
            ctx.flag = True
        elif msg=='查看铸币':
            text=self._read_bank()
            ctx.flag = True
        self.reply(ctx,text)
        return ctx

class FeatureDeepSeek(Feature):
    name = FeatureName.DEEPSEEK
    priority = 2
    abstract = False
    def function(self,ctx:Context) ->Context:
        msg:str=ctx.msg
        text=''
        if msg.startswith('%') and len(msg) > 2:
            text = deepseek.deepseek_dialogue(msg[1:])
            ctx.flag = True
        elif msg == '查看余额':
            text = deepseek.deepseek_balance()
            ctx.flag = True
        self.reply(ctx,text)
        return ctx

class FeatureRecord(Feature):
    name = FeatureName.RECORD
    priority = 3
    abstract = False

    def __init__(self):
        self.record_file = '../json/记录.json'
        self.archived_file = '../json/归档记录.json'

    def _archive_records(self,group:str)->str:
        try:
            with open(self.record_file, 'r', encoding='utf-8') as f:
                records = json.load(f)
            with open(self.archived_file, 'r', encoding='utf-8') as f:
                archived = json.load(f)
        except FileNotFoundError:
            return '记录文件不存在，无需归档'
        except json.JSONDecodeError:
            return '记录文件损坏，无法读取'

        current = records.get(group, [])
        if not current:
            return '当前没有可归档的记录'

        # 合并到归档
        if group in archived:
            archived[group].extend(current)
        else:
            archived[group] = current
        records[group] = []

        # 原子写入
        try:
            self._safe_write_json(self.record_file, records)
            self._safe_write_json(self.archived_file, archived)
        except OSError as e:
            return f'归档写入失败：{e}'

        return f'已归档 {len(current)} 条记录'

    @staticmethod
    def _safe_write_json(filepath, data):
        tmp_path = filepath + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, filepath)

    def admin_action(self,action:str,**kwargs) ->str:
        if action==AdminCMD.ARCHIVE_RECORD:
            group=kwargs[Name.GROUP]
            if group:
                return self._archive_records(str(group))
            else:
                return '该管理功能只能在群聊中使用'
        else:
            return '未知的管理指令'

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg
        group: int = ctx.group_id
        admin: list[int] = ctx.admin
        super_admin: int = ctx.super_admin
        qq: int = ctx.qq
        blacklist: list[int] = ctx.blacklist
        nickname:str=ctx.nickname
        text=''
        if ctx.msg_type != Name.GROUP:
            return ctx
        if msg.startswith('记录 '):
            i = {'name': nickname, 'uin': qq, 'content': msg[3:], 'time': time.time()}
            text=record.record(i, group)
            ctx.flag = True
        elif len(msg) > 5 and msg.startswith('删除记录 '):
            num= msg[5:]
            text=record.delete_record(num, group, qq, super_admin, admin)
            ctx.flag = True
        elif '[CQ:reply' in msg:
            m = re.sub(r'\[.*?]', '', msg)
            m = m.replace(' ', '')
            if m == '记录':
                match = re.search(r'CQ:reply,id=(\d+)', msg)
                msg_id = match.group(1)
                text=record.record_id(msg_id, blacklist)
                ctx.flag = True
        elif msg == '查看记录':
            record.read_record(group, 1, 0)
            ctx.flag = True
        elif msg == '记录查看':
            record.read_record(group, 2, 0)
            ctx.flag = True
        elif msg == '查看历史记录':
            record.read_record(group, 4, 0)
            ctx.flag = True
        elif len(msg) > 4 and msg.startswith('查看记录'):
            record.read_record(group, 3, msg[4:])
            ctx.flag = True

        if text:
            ctx.send_msg.append({'msg_type': Name.GROUP, 'number': group, 'msg': text})
        return ctx

class FeatureRoulette(Feature):
    name = FeatureName.ROULETTE
    priority = 4
    abstract = False
    def __init__(self):
        self.manager=roulette.roulette.Manager()

    def reset_cache(self):
        self.manager = roulette.roulette.Manager()

    def admin_action(self,action:str,**kwargs) ->str:
        if action==AdminCMD.END_ROULETTE:
            self.manager=roulette.roulette.Manager()
            return '已重置轮盘'
        else:
            return '未知指令'

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg
        group: int = ctx.group_id
        qq: int = ctx.qq
        nickname: str = ctx.nickname
        msg_type: str = ctx.msg_type

        if msg_type!=Name.GROUP:
            return ctx

        handler = self.manager.get_handler(group)
        replies = handler.process(qq, msg, nickname)
        private_msgs = handler.fetch_flush_private()
        if replies or private_msgs:
            for text in replies:
                ctx.send_msg.append({'msg_type': Name.GROUP,
                                           'number': group, 'msg': text})
            for target_user_id, private_text in private_msgs:
                ctx.send_msg.append({'msg_type': Name.PRIVATE,
                                           'number': target_user_id, 'msg': private_text})
            ctx.flag = True
        if msg == '轮盘帮助':
            with open('../文档/俄罗斯轮盘.txt', 'r', encoding='utf-8') as f:
                text = f.read()
            ctx.send_msg.append({'msg_type': Name.GROUP,
                                           'number': group, 'msg': text})
            ctx.flag = True

        return ctx

class FeatureOPjokes(Feature):
    name = FeatureName.OPJOKES
    priority = 5
    abstract = False
    def __init__(self):
        with open("../文档/op段子.txt", "r", encoding="utf-8") as f:
            self.op_jokes= f.read().splitlines()

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg

        text:str=''
        if msg == "op段子":
            text = random.choice(self.op_jokes)
            ctx.flag = True
        self.reply(ctx,text)
        return ctx

class FeatureImages(Feature):
    name = FeatureName.IMAGE
    priority = 6
    abstract = False
    def __init__(self):
        with open("../文档/image.txt", "r", encoding="utf-8") as f:
            self.images= {line.split(",")[0]: line.split(",")[1].rstrip('\n') for line in f}


    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg

        processed = re.sub(r'\[.*?]', '', msg).replace(' ', '')
        text=''
        if processed in self.images:
            image_name=self.images[processed]
            if processed == '怒怒':
                if random.randint(0, 1) == 1:
                    image_name = "怒怒.jpg"
                else:
                    image_name="怒怒1.jpg"
            elif processed == '歪歪旋转':
                if random.randint(0, 1) == 1:
                    image_name="歪歪旋转0.gif"
                else:
                    image_name="歪歪旋转1.gif"
            text = "[CQ:image,file=file:///" + os.path.dirname(os.getcwd()) + "/图片/" + image_name+ "]"
            ctx.flag = True
        elif msg == "图片列表":
            items = [i for i in self.images if '帮助' not in i]
            text="图片列表：" + "，".join(items)
            ctx.flag = True
        self.reply(ctx,text)
        return ctx

class FeatureDice(Feature):
    name = FeatureName.DICE
    priority = 7
    abstract = False

    def function(self, ctx: Context) -> Context:
        msg: str = ctx.msg
        text = ''
        if msg.startswith('d') or msg.startswith('D'):
            msg_fixed = msg.replace('（', '(').replace('）', ')')
            if len(msg_fixed) > 50 or not re.fullmatch(r'[0-9-+*dD()]+', msg_fixed):
                result = None
            else:
                def convert_dice(match):
                    num = match.group(1)  # 可能是空字符串或数字
                    sides = match.group(2)
                    count = num if num else '1'
                    return "+".join([f"d({sides})"] * int(count))
                converted = re.sub(r'(\d*)[dD](\d+)', convert_dice, msg_fixed)

                try:
                    # 创建安全计算器，注册 d(面数) 函数
                    evaluator = SimpleEval()
                    evaluator.functions["d"] = lambda sides: random.randint(1, int(sides))
                    result = evaluator.eval(converted)
                except Exception:
                    result = None
            if result is not None:
                text = str(result)
                ctx.flag = True

        self.reply(ctx, text)
        return ctx

class FeatureCapoo(Feature):
    name = FeatureName.CAPOO
    priority = 8
    abstract = False
    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg

        text=''
        if msg in ["咖波", "capoo"]:
            ran = random.choice(os.listdir(os.path.dirname(os.getcwd()) + r"/capoo"))
            text = "[CQ:image,file=file:///" + os.path.dirname(os.getcwd()) + r"/capoo" + "/" + ran + "]"
            ctx.flag = True

        self.reply(ctx,text)
        return ctx

class FeatureHSDjokes(Feature):
    name = FeatureName.HSDJOKES
    priority = 9
    abstract = False
    def __init__(self):
        self.hsd_jokes= os.listdir(os.path.dirname(os.getcwd()) + "/hsd笑话")
    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg

        text=''
        if msg == 'hsd笑话' or msg == 'HSD笑话':
            ran = random.choice(self.hsd_jokes)
            text = "[CQ:image,file=file:///" + os.path.dirname(os.getcwd()) + r"/hsd笑话" + "/" + ran + "]"
            self.hsd_jokes.remove(ran)
            if len(self.hsd_jokes) == 0:
                self.hsd_jokes= os.listdir(os.path.dirname(os.getcwd()) + "/hsd笑话")
            ctx.flag = True

        self.reply(ctx,text)
        return ctx

class FeatureBottleMail(Feature):
    name = FeatureName.BOTTLE_MAIL
    priority = 10
    abstract = False
    def __init__(self):
        self.db_route='../database/bottle_mail.db'
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''create table if not exists bottle_mail(
            id integer PRIMARY KEY AUTOINCREMENT,
            content text NOT NULL,
            create_time timestamp default current_timestamp
                   );
            '''
            cursor.execute(sql)
            sql='''create table if not exists hold_bottle(
            user_id integer primary key,
            content text NOT NULL);
            '''
            cursor.execute(sql)

    def _add_bottle(self,content):
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''insert into bottle_mail(content) values (?);'''
            cursor.execute(sql, (content,))
            conn.commit()

    def _fetch_bottle(self)->str|None:
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''select id,content from bottle_mail order by random() limit 1;'''
            cursor.execute(sql)
            row = cursor.fetchone()
            if not row:
                return None
            bottle_id,content = row
            sql='''delete from bottle_mail where id=?;'''
            cursor.execute(sql, (bottle_id,))
            conn.commit()
            return content

    def _get_hold(self,user_id)->str|None:
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''select content from hold_bottle where user_id = ?;'''
            cursor.execute(sql, (user_id,))
            content = cursor.fetchone()
            return content[0] if content else None

    def _set_hold(self, user_id: int, content: str):
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''replace into hold_bottle(user_id, content) VALUES (?, ?);'''
            cursor.execute(sql, (user_id, content))
            conn.commit()

    def _delete_hold(self, user_id: int) -> bool:
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''DELETE FROM hold_bottle WHERE user_id = ?;'''
            cursor.execute(sql, (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def _return_bottle(self, user_id: int):
        content = self._get_hold(user_id)
        if not content:
            return False
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''INSERT INTO bottle_mail (content) VALUES (?);'''
            cursor.execute(sql, (content,))
            sql='''delete from hold_bottle where user_id = ?;'''
            cursor.execute(sql, (user_id,))
            conn.commit()
            return True

    def _count_bottle(self)->int:
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''select count(*) from bottle_mail;'''
            cursor.execute(sql)
            row = cursor.fetchone()
            if not row:
                return 0
            else:
                return row[0]

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg
        qq:int=ctx.qq
        text=''

        ctx.flag=True
        if msg.startswith('丢漂流瓶 '):
            if len(msg)>=6:
                self._add_bottle(msg[5:])
                text='已丢入漂流瓶海'
            else:
                text='要丢什么呢？'
        elif msg=='捞漂流瓶':
            hold=self._get_hold(qq)
            if hold:
                text=f'你还有一个未处理的漂流瓶，内容是\n{hold}\n请选择扔漂流瓶或砸漂流瓶'
            else:
                bottle=self._fetch_bottle()
                if bottle:
                    self._set_hold(qq,bottle)
                    text=f'你捞到了一个漂流瓶，内容是：\n{bottle}'
                else:
                    text='漂流瓶海里已经没有漂流瓶了'
        elif msg=='砸漂流瓶':
            if self._delete_hold(qq):
                text='漂流瓶已经被砸掉'
            else:
                text='你还没有捞漂流瓶'
        elif msg=='扔漂流瓶':
            if self._return_bottle(qq):
                text='漂流瓶已经被扔回漂流瓶海'
            else:
                text='你还没有捞漂流瓶'
        elif msg=='漂流瓶海':
            text=f'漂流瓶海里有{self._count_bottle()}个漂流瓶'
        else:
            ctx.flag=False

        self.reply(ctx,text)
        return ctx

class FeatureRabble(Feature):
    name = FeatureName.RABBLE
    priority = 11
    abstract = False

    def __init__(self):
        self._games: dict[int, rabble.RabbleGame] = {}
        self._questions: dict[int, object] | None = None
        self._question_path:str='../文档/乌合之众.txt'

    def reset_cache(self):
        """Clear all in-progress games."""
        self._games.clear()

    def _find_conflict_game(self, qq: int, exclude_group: int) -> int | None:
        """Return group_id if qq is already in another group's game, else None."""
        for gid, g in self._games.items():
            if gid == exclude_group:
                continue
            if qq in g.players:
                return gid
        return None
    def _ensure_questions(self):
        if self._questions is None:
            self._questions = rabble.load_questions(self._question_path)

    def function(self, ctx: Context) -> Context:
        msg: str = ctx.msg.strip()
        qq: int = ctx.qq
        group_id: int = ctx.group_id
        msg_type: str = ctx.msg_type

        if msg_type == "private":
            self._handle_private(ctx, msg, qq)
            return ctx

        if msg_type != "group":
            return ctx

        self._ensure_questions()

        if group_id not in self._games:
            g = rabble.RabbleGame()
            g.group_id = group_id
            self._games[group_id] = g

        game = self._games[group_id]

        if game.is_waiting():
            self._handle_waiting(ctx, game, msg, qq, group_id)
        elif game.is_playing():
            self._handle_playing(ctx, game, msg, qq, group_id)
        return ctx

    def _handle_waiting(self, ctx, game, msg, qq, group_id):
        if msg == rabble.CMD_JOIN:
            conflict = self._find_conflict_game(qq, group_id)
            if conflict is not None:
                self.reply(ctx, f'你已在群{conflict}的游戏中，请先退出')
                ctx.flag = True
                return
            result = game.add_player(qq, ctx.nickname)
            self.reply(ctx, result)
            ctx.flag = True
        elif msg == rabble.CMD_LEAVE:
            result = game.remove_player(qq)
            self.reply(ctx, result)
            ctx.flag = True
        elif msg == rabble.CMD_START:
            if qq not in game.players:
                self.reply(ctx, "你还没有加入游戏")
                ctx.flag = True
                return
            start_msg = game.start(self._questions, rabble.DEFAULT_TURN)
            if start_msg:
                ctx.send_msg.append({"msg_type": "group", "number": group_id, "msg": start_msg})
            ctx.flag = True
        else:
            ctx.flag = False

    def _handle_playing(self, ctx, game, msg, qq, group_id):
        if msg == rabble.CMD_REMIND:
            for p in game.unanswered_players():
                ctx.send_msg.append({"msg_type": "private", "number": p, "msg": "速度"})
            ctx.flag = True
        elif msg == rabble.CMD_BLIND:
            game.blind_select()
            self._advance_or_finish(ctx, group_id, game)
            ctx.flag = True
        else:
            ctx.flag = False

    def _handle_private(self, ctx, msg, qq):
        for group_id, game in self._games.items():
            if not game.is_playing():
                continue
            if qq not in game.players:
                continue
            result = game.submit_answer(qq, msg, self._questions)
            if result is None:
                continue
            ctx.send_msg.append({"msg_type": "private", "number": qq, "msg": result})
            ctx.flag = True
            if game.all_answered():
                self._advance_or_finish(ctx, group_id, game)
            break

    def _advance_or_finish(self, ctx, group_id, game):
        next_q = game.advance_question(self._questions)
        if next_q is None:
            self._finish_game(ctx, group_id, game)
        else:
            ctx.send_msg.append({"msg_type": "group", "number": group_id, "msg": next_q})

    def _finish_game(self, ctx, group_id, game):
        scores, answer_strs, dists = game.calculate_scores()
        for msg_text in game.build_result_messages(scores, answer_strs, dists):
            ctx.send_msg.append({"msg_type": "group", "number": group_id, "msg": msg_text})
        self._games[group_id] = rabble.RabbleGame()
        self._games[group_id].group_id = group_id

class FeatureRepeaterDetection(Feature):
    name = FeatureName.REPEATER_DETECTION
    priority = 12
    abstract = False

    def __init__(self):
        self.db_route='../database/posted_images.db'
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql='''
                create table if not exists posted_images (
                image_uuid text,
                group_id integer
                );
                '''
            cursor.execute(sql)

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg
        group: int= ctx.group_id
        msg_type:str = ctx.msg_type

        text=''
        if msg_type!=Name.GROUP:
            return ctx
        if re.fullmatch(r'\[CQ:image[^\[\]]*]',msg):
            image_uuid=re.search(r'file=([^,]+),',msg).group(1)
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql='select * from posted_images where image_uuid=? and group_id=?;'
                cursor.execute(sql, (image_uuid, group))
                if len(cursor.fetchall()) == 0:
                    sql='insert into posted_images (image_uuid, group_id) values (?, ?);'
                    cursor.execute(sql, (image_uuid, group))
                else:
                    ctx.flag = True
                    text='发过了'
        self.reply(ctx,text)
        return ctx

class FeatureQueryMiaoKa(Feature):
    name = 'query_miaoka'
    abstract = False
    priority = 13

    def __init__(self):
        self.db_route='../database/miaoka.db'

    def query_by_se(self,season: int, episode: int) -> str:
        """查询指定季数、期数。"""
        with sqlite3.connect(self.db_route) as conn:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                """SELECT season, episode, title, post_url, requirement, pub_date
                   FROM miaoka_contest WHERE season = ? AND episode = ?""",
                (season, episode)
            ).fetchone()
        if result is None:
            return '没有查询到对应的喵赛。'
        result=dict(result)
        text=(f"喵卡周赛 第{result['season']}季 第{result['episode']}期"
              f"\n标题: {result['title']}\n链接: {result['post_url']}\n"
              f"发布日期: {result.get('pub_date', '未知')}\n"
              f"本期要求:\n{result['requirement'] or '(未提取到)'}")
        return text

    def query_random(self) -> str:
        """查询指定季数、期数。"""
        with sqlite3.connect(self.db_route) as conn:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                """SELECT season, episode, title, post_url, requirement, pub_date
                   FROM miaoka_contest order by random() limit 1""",
            ).fetchone()
        result=dict(result)
        text=(f"喵卡周赛 第{result['season']}季 第{result['episode']}期"
              f"\n标题: {result['title']}\n链接: {result['post_url']}\n"
              f"发布日期: {result.get('pub_date', '未知')}\n"
              f"本期要求:\n{result['requirement'] or '(未提取到)'}")
        return text

    def function(self,ctx:Context) ->Context:
        msg: str = ctx.msg
        pattern = re.compile(r'^查询喵赛 (\d+) (\d+)$')
        match = pattern.match(msg)
        text=''
        if match:
            season= int(match.group(1))
            issue= int(match.group(2))
            text=self.query_by_se(season,issue)
            ctx.flag=True
        elif msg=='随机喵赛':
            text=self.query_random()
            ctx.flag=True
        self.reply(ctx,text)
        return ctx

class FeatureRepeat(Feature):
    name = FeatureName.REPEAT
    priority = 98
    abstract = False
    def __init__(self):
        self.repeat_dict:dict[int,list[str]]={}

    def reset_cache(self):
        self.repeat_dict.clear()
    def function(self,ctx:Context) ->Context:
        msg:str=ctx.msg
        group: int = ctx.group_id
        if ctx.msg_type!=Name.GROUP:
            return ctx
        if msg.endswith("喵"):
            if group not in self.repeat_dict:
                self.repeat_dict[group]=[]
            if len(self.repeat_dict[group]) >= 3:
                del self.repeat_dict[group][0]
            if msg not in self.repeat_dict[group]:
                ctx.send_msg.append({'msg_type': Name.GROUP, 'number': group, 'msg':msg})
            self.repeat_dict[group].append(msg)
            ctx.flag=True
        return ctx

class FeatureDefine(Feature):
    name = FeatureName.DEFINE
    priority = 99
    abstract = False

    def __init__(self):
        self.define_dict:dict[str,str]=self._read_define()
        self.used:dict[int,dict[str,int]]={}
    def reset_cache(self):
        self.used.clear()

    @staticmethod
    def _read_define():
        with open('../json/define.json', 'r') as f:
            define_list= json.load(f)
        return define_list

    def _write_define(self):
        with open('../json/define.json', 'w') as f:
            json.dump(self.define_dict, f)

    def admin_action(self,action:str,**kwargs) ->str:
        if action==AdminCMD.DELETE_DEFINE:
            keyword=kwargs[Name.ARG]
            if keyword in self.define_dict:
                del self.define_dict[keyword]
                self._write_define()
                return '已删除'
            else:
                return f'不存在关键词为{keyword}的定义'
        else:
            return '未知的管理指令'

    def function(self,ctx:Context) ->Context:
        msg:str=ctx.msg
        group:int=ctx.group_id
        admin:list[int]=ctx.admin
        qq:int=ctx.qq
        if ctx.msg_type!=Name.GROUP:
            return ctx

        if msg.startswith("定义") and "=" in msg:
            idx=msg.find('=')
            keyword = msg[2:idx]
            if msg[2:idx] in self.define_dict and qq not in admin and qq != ctx.super_admin:
                ctx.send_msg.append({'msg_type': Name.GROUP,'number': group, 'msg': '关键词已被定义'})
            elif idx> 17:
                ctx.send_msg.append({'msg_type': Name.GROUP,'number': group, 'msg': '关键词太长了'})
            elif '[CQ:' in keyword:
                ctx.send_msg.append({'msg_type': Name.GROUP, 'number': group,'msg': '关键词不能包含特殊消息'})
            elif idx != 2 and idx != len(msg)- 1 and ' ' not in keyword and msg[-1]!='喵':
                content = msg[idx + 1:]
                self.define_dict[keyword] =content
                self._write_define()
                ctx.send_msg.append({'msg_type': Name.GROUP, 'number': group,'msg': content+ '喵'})
        elif msg == "查看定义":
            text = ""
            for i in self.define_dict:
                if '[CQ:at' not in self.define_dict[i]:
                    text = text + i + "=" + self.define_dict[i] + "\n"
            ctx.send_msg.append({'msg_type': Name.GROUP,'number': group, 'msg': text})
        elif re.sub(r'\[.*?]', '', msg).replace(' ', '') in self.define_dict:
            clean_msg=re.sub(r'\[.*?]', '', msg).replace(' ', '')
            if group not in self.used:
                self.used[group] = {}
            if clean_msg not in self.used[group]:
                self.used[group][clean_msg] = 0
            if time.time() - self.used[group][clean_msg] > 10:
                ctx.send_msg.append({'msg_type': Name.GROUP, 'number': group, 'msg': self.define_dict[clean_msg]})
                self.used[group][clean_msg] = int(time.time())
        return ctx

def get_all_subclasses(cls):
    """递归获取一个类的所有后代子类（包括间接子类）"""
    subclasses = set()
    for sub in cls.__subclasses__():
        subclasses.add(sub)
        subclasses.update(get_all_subclasses(sub))
    return subclasses

class BotCore:
    def __init__(self):
        self._options_file = "../文档/options.txt"
        self._admin_file = "../json/administrators.json"
        self._blacklist_file = "../json/黑名单.json"
        self.black_list:list[int]=read_json(self._blacklist_file)
        self.admin: list[int] = read_json(self._admin_file)
        self.options:dict[str,int]=self._read_options()
        self.super_admin:int=SUPERADMIN
        self.own_id:int=read_id()
        self.plugins:list[Plugin]= self._load_and_sort_plugins()
        self.features: list[Feature] = cast(list[Feature],
                                [p for p in self.plugins if p.plugin_type == PluginName.FEATURE])
        self.event_handlers: list[EventHandler] = cast(list[EventHandler],
                                [p for p in self.plugins if p.plugin_type == PluginName.EVENT_HANDLER])
        self.feature_map = {f.name: f for f in self.features}

    def _read_options(self):
        options = {}
        with open(self._options_file, "r", encoding="utf-8") as f:
            for line in f:
                key, value = line.strip().split("=")
                options[key] = int(value)
        return options

    def _load_and_sort_plugins(self) -> list[Plugin]:
        all_classes = get_all_subclasses(Plugin)  # 拿到 Plugin 的所有后代
        plugins = []

        for cls in all_classes:
            if cls.abstract:  # 跳过带 abstract=True 的基类
                continue
            if not cls.name:  # 必须有 name
                continue

            # 特殊处理：管理模块需要 AdminAPI
            if cls == FeatureAdmin:
                api = AdminAPI(
                    set_option=self._set_option,
                    appoint_admin=self._appoint_admin,
                    block_user=self._block_user,
                    feature_action=self._feature_action,
                    reset_all=self._reset_all_plugins,
                )
                plugins.append(cls(api=api))
            else:
                plugins.append(cls())

        plugins.sort(key=lambda p: p.priority)
        return plugins

    def _set_option(self,name:str, value:int)->str:
        if name==FeatureName.ADMIN:
            return '不允许关闭管理功能'
        self.options[name] = value
        with open(self._options_file, "w", encoding="utf-8") as f:
            for k, v in self.options.items():
                f.write(f"{k}={v}\n")
        return '已执行'

    def _appoint_admin(self,qq:int, value:int)->str:
        if value and qq not in self.admin:
            self.admin.append(qq)
        elif not value and qq in self.admin:
            self.admin.remove(qq)
        else:
            return '指令错误'

        with open(self._admin_file, "w", encoding="utf-8") as f:
            json.dump(self.admin, f, ensure_ascii=False, indent=2)
        return '已执行'

    def _block_user(self,qq:int, value:int)->str:
        if value and qq not in self.black_list:
            self.black_list.append(qq)
        elif not value and qq in self.black_list:
            self.black_list.remove(qq)
        else:
            return '指令错误'
        with open(self._blacklist_file, "w", encoding="utf-8") as f:
            json.dump(self.black_list, f, ensure_ascii=False, indent=2)
        return '已执行'

    def _reset_all_plugins(self) -> str:
        count = 0
        for p in self.plugins:
            p.reset_cache()
            count += 1
        return f'已清理{count}个模块的缓存'

    def _feature_action(self, feature_name: str, action: str, **kwargs)->str:
        feature = self.feature_map.get(feature_name)
        if not feature:
            return f"不存在功能：{feature_name}"

        try:
            return feature.admin_action(action, **kwargs)
        except Exception as e:
            # 记录日志（可选）
            return f"操作失败：{str(e)}"

    def handle(self,event):
        if event['post_type'] == 'message':

            ctx:Context=Context(
                qq=event['sender']['user_id'],
                group_id=event.get('group_id',0),
                msg=event['raw_message'].replace('\r\n', '\n'),
                msg_type=event["message_type"],
                nickname=event['sender']['nickname'],
                flag=False,
                send_msg=[],
                admin=self.admin.copy(),
                super_admin=self.super_admin,
                blacklist=self.black_list.copy(),
                options=self.options.copy()
            )

            if ctx.qq==self.own_id or ctx.qq in self.black_list or DELIMITER in ctx.msg:
                ctx.flag=True
            else:
                for feature in self.features:
                    if not feature.is_enabled(ctx.options):
                        continue
                    ctx = feature.function(ctx)
                    if ctx.flag:
                        break

            for i in ctx.send_msg:
                send_msg(i)

        else:
            ctx:MiniContext=MiniContext(
                own_id=self.own_id
            )
            for event_handler in self.event_handlers:
                if not event_handler.is_enabled(self.options.copy()):
                    continue
                if event_handler.handle_event(event, ctx):
                    break
