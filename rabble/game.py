import random

from rabble.constant import DEFAULT_TURN, Answer, ANSWER_CHAR
from rabble.question import (
    Question, QuestionScorer, get_scorer,
    load_questions, generate_ranking,
    _count, _int_to_chinese,
)


class RabbleGame:
    """State machine for one rabble quiz game in a single group.

    Questions are referenced by their id (from Question objects),
    NOT by position in the .txt file.
    Player answers are stored as Answer enum values;
    None means unanswered.
    """

    _UNANSWERED = None  # sentinel for unanswered

    def __init__(self):
        self.players: dict[int, str] = {}
        self.answers: dict[int, list[Answer | None]] = {}
        self.state: int = 0
        self._qids: list[int] = []
        self._current_turn: int = 0
        self.miss: set[int] = set()
        self.group_id: int = 0
        self.turn_count: int = DEFAULT_TURN

    # ---- State queries ----

    def is_waiting(self) -> bool:
        return self.state == 0

    def is_playing(self) -> bool:
        return self.state == 1

    @property
    def current_question_id(self) -> int | None:
        if self._current_turn < len(self._qids):
            return self._qids[self._current_turn]
        return None

    # ---- Player management ----

    async def add_player(self, qq: int, name: str) -> str:
        if qq in self.players:
            return '你已加入游戏，请不要重复加入'
        self.players[qq] = name
        self.answers[qq] = []
        return '已加入游戏'

    async def remove_player(self, qq: int) -> str:
        if qq not in self.players:
            return '你还没有加入游戏'
        del self.players[qq]
        del self.answers[qq]
        return '已退出游戏'

    # ---- Game flow ----

    async def start(self, questions: dict[int, Question],
                    turn: int = DEFAULT_TURN) -> str | None:
        if len(self.players) < 2:
            return '未满2个人'

        all_ids = list(questions.keys())
        self.turn_count = min(turn, len(all_ids))
        chosen = random.sample(all_ids, self.turn_count)
        self._qids = chosen
        self.answers = {
            qq: [self._UNANSWERED] * self.turn_count
            for qq in self.players
        }
        self.state = 1
        self._current_turn = 0
        self.miss = set()

        first_q = questions[self._qids[0]]
        return f"共有{len(self.players)}人参加\n第1题：\n{first_q.text}"

    async def submit_answer(self, qq: int, answer: str,
                            questions: dict[int, Question]) -> str | None:
        if qq not in self.players:
            return '你还没有加入游戏'
        qid = self.current_question_id
        if qid is None:
            return None
        q = questions.get(qid)
        if q is None:
            return None
        ans = q.validate(answer)
        if ans is None:
            return None

        old = self.answers[qq][self._current_turn]
        self.answers[qq][self._current_turn] = ans
        if old is self._UNANSWERED:
            return f'已获取答案{ANSWER_CHAR[ans]}'
        return f'已修改为{ANSWER_CHAR[ans]}'

    async def all_answered(self) -> bool:
        for qq in self.players:
            if self.answers[qq][self._current_turn] is self._UNANSWERED \
                    and qq not in self.miss:
                return False
        return True

    async def unanswered_players(self) -> list[int]:
        return [qq for qq in self.players
                if self.answers[qq][self._current_turn] is self._UNANSWERED
                and qq not in self.miss]

    async def advance_question(self, questions: dict[int, Question]) -> str | None:
        self._current_turn += 1
        if self._current_turn >= self.turn_count:
            return None
        qid = self._qids[self._current_turn]
        q = questions[qid]
        return f"第{_int_to_chinese(self._current_turn + 1)}题：\n{q.text}"

    async def blind_select(self):
        unanswered = await self.unanswered_players()
        for qq in unanswered:
            self.answers[qq][self._current_turn] = random.choice(
                [Answer.A, Answer.B, Answer.C]
            )
            self.miss.add(qq)

    # ---- Scoring ----

    async def calculate_scores(self) -> tuple[dict[int, float],
                                              dict[int, str],
                                              list[list[int]]]:
        scores: dict[int, float] = {qq: 0.0 for qq in self.players}
        answer_strs: dict[int, str] = {}
        distributions: list[list[int]] = []

        for turn_idx, qid in enumerate(self._qids):
            ans_for_q: dict[int, Answer] = {}
            for qq in self.players:
                ans_for_q[qq] = self.answers[qq][turn_idx]

            scorer = get_scorer(qid)
            if scorer is not None:
                scorer.score(ans_for_q, scores)

            a, b, c, d = _count(ans_for_q)
            distributions.append([a, b, c, d])

        for qq in self.miss:
            scores[qq] -= 1

        for qq in self.players:
            answer_strs[qq] = ''.join(
                ANSWER_CHAR[self.answers[qq][i]] for i in range(self.turn_count)
            )

        return scores, answer_strs, distributions

    async def build_result_messages(self, scores: dict[int, float],
                                    answer_strs: dict[int, str],
                                    distributions: list[list[int]]) -> list[str]:
        msgs = ['游戏结束']
        msgs.append(await generate_ranking(scores, self.players))

        ans_text = ''
        for qq in self.players:
            ans_text += f'{self.players[qq]}：{answer_strs[qq]}\n'
        msgs.append(ans_text)

        dist_text = '选项分布情况：\n'
        for i in range(self.turn_count):
            a, b, c, d = distributions[i]
            dist_text += f'第{_int_to_chinese(i + 1)}题：'
            if a: dist_text += f'{a}A'
            if b: dist_text += f'{b}B'
            if c: dist_text += f'{c}C'
            if d: dist_text += f'{d}D'
            dist_text += '\n'
        msgs.append(dist_text)
        return msgs
