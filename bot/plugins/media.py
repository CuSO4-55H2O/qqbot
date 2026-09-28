from __future__ import annotations

import asyncio
import os
import re
import random
import sqlite3

from bot.plugin import Deps, Matcher, register
from bot.request import EmojiLike, Outcome, Reply, Request
from constant import *


@register
class FeatureImages(Matcher):
    name = FeatureName.IMAGE
    priority = 5
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        with open(DocPath.IMAGE_TXT, "r", encoding="utf-8") as f:
            self.images = {line.split(",")[0]: line.split(",")[1].rstrip('\n') for line in f}

    async def match(self, req: Request) -> Reply | None:
        processed = re.sub(r'\[.*?]', '', req.msg).replace(' ', '')
        if processed in self.images:
            image_name = self.images[processed]
            if processed == '怒怒':
                image_name = "怒怒.jpg" if random.randint(0, 1) == 1 else "怒怒1.jpg"
            elif processed == '歪歪旋转':
                image_name = "歪歪旋转0.gif" if random.randint(0, 1) == 1 else "歪歪旋转1.gif"
            return Reply.same_conversation(
                req, "[CQ:image,file=file:///" + MediaDir.IMAGE + "/" + image_name + "]")
        if req.msg == "图片列表":
            items = [i for i in self.images if '帮助' not in i]
            return Reply.same_conversation(req, "图片列表：" + "，".join(items))
        return None


@register
class FeatureCapoo(Matcher):
    name = FeatureName.CAPOO
    priority = 7
    abstract = False

    async def match(self, req: Request) -> Reply | None:
        if req.msg in ("咖波", "capoo"):
            ran = random.choice(os.listdir(MediaDir.CAPOO))
            return Reply.same_conversation(
                req, "[CQ:image,file=file:///" + MediaDir.CAPOO + "/" + ran + "]")
        return None


@register
class FeatureHSDjokes(Matcher):
    name = FeatureName.HSDJOKES
    priority = 8
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.hsd_jokes = self.get_hsd_jokes()

    @staticmethod
    def get_hsd_jokes():
        return os.listdir(MediaDir.HSD)

    async def reset_cache(self):
        self.hsd_jokes = self.get_hsd_jokes()

    async def match(self, req: Request) -> Reply | None:
        if req.msg not in ('hsd笑话', 'HSD笑话'):
            return None
        ran = random.choice(self.hsd_jokes)
        self.hsd_jokes.remove(ran)
        if not self.hsd_jokes:
            self.hsd_jokes = self.get_hsd_jokes()
        return Reply.same_conversation(
            req, "[CQ:image,file=file:///" + MediaDir.HSD + "/" + ran + "]")


@register
class FeatureRepeaterDetection(Matcher):
    name = FeatureName.REPEATER_DETECTION
    priority = 11
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.db_route = DBPath.POSTED_IMAGES
        with sqlite3.connect(self.db_route) as conn:
            cursor = conn.cursor()
            sql = '''
                create table if not exists posted_images (
                image_uuid text,
                group_id integer
                );
                '''
            cursor.execute(sql)

    async def match(self, req: Request) -> Reply | None:
        if not req.is_group:
            return None
        if not re.fullmatch(r'\[CQ:image[^\[\]]*]', req.msg):
            return None
        image_uuid = re.search(r'file=([^,]+),', req.msg).group(1)
        group = req.group_id

        def _sync():
            with sqlite3.connect(self.db_route) as conn:
                cursor = conn.cursor()
                sql = 'select * from posted_images where image_uuid=? and group_id=?;'
                cursor.execute(sql, (image_uuid, group))
                if len(cursor.fetchall()) == 0:
                    sql = 'insert into posted_images (image_uuid, group_id) values (?, ?);'
                    cursor.execute(sql, (image_uuid, group))
                    return ''
                return '发过了'

        text = await asyncio.to_thread(_sync)
        # 第一次见到这张图：只记下，不回话，也**不算接住** —— 它会照常进语料库
        return Reply.same_conversation(req, text) if text else None


@register
class FeatureEmojiReaction(Matcher):
    name = FeatureName.EMOJI_REACTION
    priority = 13
    abstract = False

    async def match(self, req: Request) -> Outcome | None:
        if not req.message_id:
            return None
        m = re.fullmatch(r'\[CQ:face,id=(\d+)(?:,[^\]]*)?\]', req.msg.strip())
        if not m:
            return None
        return Outcome.handled(EmojiLike(message_id=req.message_id, emoji_id=m.group(1)))
