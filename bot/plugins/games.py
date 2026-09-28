from __future__ import annotations

import asyncio
import roulette.roulette
import rabble

from bot.plugin import Deps, Feature, register
from bot.request import Outcome, Reply, Request
from constant import *


@register
class FeatureRoulette(Feature):
    name = FeatureName.ROULETTE
    priority = 3
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.user_id = deps.own_id
        self.nickname = deps.own_nickname
        self.manager = roulette.roulette.Manager(
            ai_user_id=self.user_id, ai_nickname=self.nickname
        )

    async def reset_cache(self):
        if hasattr(self, 'manager'):
            for handler in self.manager.handlers.values():
                await handler.close()
        self.manager = roulette.roulette.Manager(
            ai_user_id=self.user_id, ai_nickname=self.nickname
        )

    async def admin_action(self, action: str, **kwargs) -> str:
        if action == AdminCMD.END_ROULETTE:
            if hasattr(self, 'manager'):
                for handler in self.manager.handlers.values():
                    await handler.close()
            self.manager = roulette.roulette.Manager(
                ai_user_id=self.user_id, ai_nickname=self.nickname
            )
            return '已重置轮盘'
        else:
            return '未知指令'

    async def function(self, req: Request) -> Outcome:
        if not req.is_group:
            return Outcome.pass_()

        handler = await self.manager.get_handler(req.group_id)
        replies = await handler.process(req.qq, req.msg, req.nickname)
        private_msgs = await handler.fetch_flush_private()

        out = [Reply(msg=text, msg_type=Name.GROUP, number=req.group_id) for text in replies]
        out.extend(Reply(msg=text, msg_type=Name.PRIVATE, number=uid)
                   for uid, text in private_msgs)

        if req.msg == '轮盘帮助':
            def _sync():
                with open(DocPath.ROULETTE, 'r', encoding='utf-8') as f:
                    return f.read()
            out.append(Reply(msg=await asyncio.to_thread(_sync),
                             msg_type=Name.GROUP, number=req.group_id))

        return Outcome.handled(*out) if out else Outcome.pass_()


@register
class FeatureRabble(Feature):
    name = FeatureName.RABBLE
    priority = 10
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self._games: dict[int, rabble.RabbleGame] = {}
        self._questions: dict[int, object] | None = None
        self._question_path: str = DocPath.RABBLE

    async def reset_cache(self):
        self._games.clear()

    def _find_conflict_game(self, qq: int, exclude_group: int) -> int | None:
        for gid, g in self._games.items():
            if gid == exclude_group:
                continue
            if qq in g.players:
                return gid
        return None

    async def _ensure_questions(self):
        if self._questions is None:
            self._questions = await rabble.load_questions(self._question_path)

    async def function(self, req: Request) -> Outcome:
        msg = req.msg.strip()

        if req.msg_type == Name.PRIVATE:
            replies = await self._handle_private(req, msg, req.qq)
            return Outcome.handled(*replies) if replies else Outcome.pass_()

        if not req.is_group:
            return Outcome.pass_()

        await self._ensure_questions()

        group_id = req.group_id
        if group_id not in self._games:
            g = rabble.RabbleGame()
            g.group_id = group_id
            self._games[group_id] = g

        game = self._games[group_id]

        if game.is_waiting():
            out = await self._handle_waiting(req, game, msg)
        elif game.is_playing():
            out = await self._handle_playing(req, game, msg)
        else:
            out = None
        return out if out is not None else Outcome.pass_()

    async def _handle_waiting(self, req, game, msg) -> Outcome | None:
        if msg == rabble.CMD_JOIN:
            conflict = self._find_conflict_game(req.qq, req.group_id)
            if conflict is not None:
                return Outcome.handled(
                    Reply.same_conversation(req, f'你已在群{conflict}的游戏中，请先退出'))
            result = await game.add_player(req.qq, req.nickname)
            return Outcome.handled(Reply.same_conversation(req, result))
        if msg == rabble.CMD_LEAVE:
            result = await game.remove_player(req.qq)
            return Outcome.handled(Reply.same_conversation(req, result))
        if msg == rabble.CMD_START:
            if req.qq not in game.players:
                return Outcome.handled(Reply.same_conversation(req, "你还没有加入游戏"))
            start_msg = await game.start(self._questions, rabble.DEFAULT_TURN)
            if start_msg:
                return Outcome.handled(Reply.same_conversation(req, start_msg))
            return Outcome.silent()
        return None

    async def _handle_playing(self, req, game, msg) -> Outcome | None:
        if msg == rabble.CMD_REMIND:
            unanswered = await game.unanswered_players()
            replies = [Reply(msg="速度", msg_type=Name.PRIVATE, number=p) for p in unanswered]
            return Outcome.handled(*replies) if replies else Outcome.silent()
        if msg == rabble.CMD_BLIND:
            await game.blind_select()
            return Outcome.handled(*await self._advance_or_finish(game, req.group_id))
        return None

    async def _handle_private(self, req, msg, qq) -> list[Reply]:
        for group_id, game in self._games.items():
            if not game.is_playing():
                continue
            if qq not in game.players:
                continue
            result = await game.submit_answer(qq, msg, self._questions)
            if result is None:
                continue
            replies = [Reply(msg=result, msg_type=Name.PRIVATE, number=qq)]
            if await game.all_answered():
                replies.extend(await self._advance_or_finish(game, group_id))
            return replies
        return []

    async def _advance_or_finish(self, game, group_id: int) -> list[Reply]:
        next_q = await game.advance_question(self._questions)
        if next_q is None:
            return await self._finish_game(game, group_id)
        return [Reply(msg=next_q, msg_type=Name.GROUP, number=group_id)]

    async def _finish_game(self, game, group_id: int) -> list[Reply]:
        scores, answer_strs, dists = await game.calculate_scores()
        out = [Reply(msg=t, msg_type=Name.GROUP, number=group_id)
               for t in await game.build_result_messages(scores, answer_strs, dists)]
        self._games[group_id] = rabble.RabbleGame()
        self._games[group_id].group_id = group_id
        return out
