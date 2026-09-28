from __future__ import annotations

import re
import random

from simpleeval import SimpleEval
from bot.plugin import Deps, Matcher, register
from bot.request import Outcome, Reply, Request
from constant import *


@register
class FeatureOPjokes(Matcher):
    name = FeatureName.OPJOKES
    priority = 4
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        with open(DocPath.OP_JOKES, "r", encoding="utf-8") as f:
            self.op_jokes = f.read().splitlines()

    async def match(self, req: Request) -> Reply | None:
        if req.msg != "op段子":
            return None
        return Reply.same_conversation(req, random.choice(self.op_jokes))


@register
class FeatureDice(Matcher):
    name = FeatureName.DICE
    priority = 6
    abstract = False

    async def match(self, req: Request) -> Reply | None:
        msg = req.msg
        if not (msg.startswith('d') or msg.startswith('D')):
            return None
        msg_fixed = msg.replace('（', '(').replace('）', ')')
        if len(msg_fixed) > 50 or not re.fullmatch(r'[0-9-+*dD()]+', msg_fixed):
            return None

        def convert_dice(match):
            num = match.group(1)
            sides = match.group(2)
            count = num if num else '1'
            return "+".join([f"d({sides})"] * int(count))

        converted = re.sub(r'(\d*)[dD](\d+)', convert_dice, msg_fixed)
        try:
            evaluator = SimpleEval()
            evaluator.functions["d"] = lambda sides: random.randint(1, int(sides))
            result = evaluator.eval(converted)
        except Exception:
            return None
        if result is None:
            return None
        return Reply.same_conversation(req, str(result))


@register
class FeatureRepeat(Matcher):
    name = FeatureName.REPEAT
    priority = 98
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.repeat_dict: dict[int, list[str]] = {}

    async def reset_cache(self):
        self.repeat_dict.clear()

    async def match(self, req: Request) -> Reply | Outcome | None:
        if not req.is_group or not req.msg.endswith("喵"):
            return None
        msg, group = req.msg, req.group_id
        bucket = self.repeat_dict.setdefault(group, [])
        if len(bucket) >= 3:
            del bucket[0]
        reply = Reply.same_conversation(req, msg) if msg not in bucket else None
        bucket.append(msg)
        # 已经复读过的仍然算「接住」（只是不再复读）—— 否则这条会掉进语料库
        return reply if reply is not None else Outcome.silent()
