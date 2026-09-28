import asyncio
import os
import re
import random
import math
from abc import ABC, abstractmethod

from rabble.constant import (
    ALLOWED_ABC, ALLOWED_ABCD,
    Answer, ANSWER_MAP, ANSWER_CHAR,
    QUESTION_FILE,
)


class Question:
    """Represents a quiz question: id + option descriptions.

    Responsible for text analysis: parsing the raw .txt block to
    determine which options are valid (A/B/C or A/B/C/D).
    Not responsible for scoring — see QuestionScorer.
    """

    __slots__ = ('id', 'text', 'allowed_answers')

    def __init__(self, qid: int, text: str):
        self.id = qid
        self.text = text
        self.allowed_answers = self._parse_allowed(text)

    def _parse_allowed(self, text: str) -> tuple[str, ...]:
        found: set[str] = set()
        for line in text.split('\n'):
            m = re.match(r'([A-E])\.', line.strip())
            if m:
                found.add(m.group(1))
        if 'D' in found and 'E' in found:
            return ('A', 'B', 'C', 'D', 'E')
        if 'D' in found:
            return ALLOWED_ABCD
        return ALLOWED_ABC

    def validate(self, answer: str) -> Answer | None:
        """Convert a player answer char to an Answer enum, or None if invalid."""
        ans = ANSWER_MAP.get(answer)
        if ans is not None and ANSWER_CHAR[ans] in self.allowed_answers:
            return ans
        return None

    def __repr__(self) -> str:
        return f'Question(id={self.id}, allowed={self.allowed_answers})'


class QuestionScorer(ABC):
    """Abstract base for question scoring rules.

    Each concrete subclass is linked to a Question via the `id` attribute.
    """

    id: int  # matches Question.id

    @abstractmethod
    def score(self, answers: dict[int, Answer],
              current_scores: dict[int, float]) -> None:
        """Mutate current_scores in-place for this question's answers."""
        ...


# ================================================================
#  Concrete scorers — one per question
# ================================================================

class _Q1Scorer(QuestionScorer):
    id = 1

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += 4 / max(b, 1)
            elif ans == Answer.C and c == min(a, b, c):
                scores[qq] += 2


class _Q2Scorer(QuestionScorer):
    id = 2

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a == min(a, b, c):
                scores[qq] += 2
            elif ans == Answer.B and b == min(a, b, c):
                scores[qq] += 2.5
            elif ans == Answer.C and c == min(a, b, c):
                scores[qq] += 3


class _Q3Scorer(QuestionScorer):
    id = 3

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 4 / max(a, 1)
            elif ans == Answer.B:
                scores[qq] += 5 / max(b, 1)
            elif ans == Answer.C:
                scores[qq] += 6 / max(c, 1)


class _Q4Scorer(QuestionScorer):
    id = 4

    def score(self, answers, scores):
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] = (scores[qq] + 4) / 2
            elif ans == Answer.C:
                scores[qq] = math.sqrt(max(scores[qq] + 8, 0))
            elif ans == Answer.D:
                scores[qq] *= 1.5


class _Q5Scorer(QuestionScorer):
    id = 5

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += 2
            elif ans == Answer.C:
                scores[qq] += (0.5 * a + 2 * b) / max(c, 1)


class _Q6Scorer(QuestionScorer):
    id = 6

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 0.5 + 0.5 * b + 0.75 * c
            elif ans == Answer.B:
                scores[qq] += 1 + a * 0.25 + 0.75 * c
            elif ans == Answer.C:
                scores[qq] += 1.5 + a * 0.25 + 0.5 * b
            elif ans == Answer.D:
                scores[qq] += a * 0.25 + 0.5 * b + 0.75 * c


class _Q7Scorer(QuestionScorer):
    id = 7

    def score(self, answers, scores):
        _, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += -2 if b > c else 2
            elif ans == Answer.C:
                scores[qq] += -3 if c >= b else 3


class _Q8Scorer(QuestionScorer):
    id = 8

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1.5 if c > 0 else -1
            elif ans == Answer.B:
                scores[qq] += 2 if a > 0 else -2
            elif ans == Answer.C:
                scores[qq] += 2.5 if b > 0 else -3
            elif ans == Answer.D:
                if a * b * c == 0:
                    scores[qq] += 1


class _Q9Scorer(QuestionScorer):
    id = 9

    def score(self, answers, scores):
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] -= 0.5
            elif ans == Answer.B:
                scores[qq] = abs(scores[qq]) - 1
            elif ans == Answer.C:
                if scores[qq] > 8:
                    scores[qq] = 0


class _Q10Scorer(QuestionScorer):
    id = 10

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B and a >= 2:
                scores[qq] += 2
            elif ans == Answer.C and b >= 3:
                scores[qq] += 3
            elif ans == Answer.D and c >= 4:
                scores[qq] += 5


class _Q11Scorer(QuestionScorer):
    id = 11

    def score(self, answers, scores):
        a, _, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a > c:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += 2 if a > c else -1
            elif ans == Answer.C:
                scores[qq] += 4 if a > c else -2


class _Q12Scorer(QuestionScorer):
    id = 12

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a < b:
                scores[qq] += 1
            elif ans == Answer.B and b < c:
                scores[qq] += 2
            elif ans == Answer.C and c < b:
                scores[qq] += 3


class _Q13Scorer(QuestionScorer):
    id = 13

    def score(self, answers, scores):
        a, b, c, d = _count(answers)
        half = (a + b + c + d) // 2
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += 2 if b >= half else -1
            elif ans == Answer.C:
                scores[qq] += 3 if c <= half else -2

class _Q14Scorer(QuestionScorer):
    id = 14

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        if c > a + b:
            outcome = 0
        elif a > b:
            outcome = 1
        elif b > a:
            outcome = 2
        else:
            outcome = 3
        for qq, ans in answers.items():
            if ans == Answer.A:
                if outcome == 0:
                    scores[qq] -= 3
                elif outcome == 1:
                    scores[qq] += 10 / max(a, 1)
            elif ans == Answer.B:
                if outcome == 0:
                    scores[qq] -= 3
                elif outcome == 2:
                    scores[qq] += 3
            elif ans == Answer.C:
                scores[qq] -= 1


class _Q15Scorer(QuestionScorer):
    id = 15

    def score(self, answers, scores):
        a, b, _, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a == 1:
                scores[qq] += 4
            elif ans == Answer.B and b == 2:
                scores[qq] += 2
            elif ans == Answer.C:
                scores[qq] += 1


class _Q16Scorer(QuestionScorer):
    id = 16

    def score(self, answers, scores):
        a, b, _, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a > b:
                scores[qq] += b * 5 / max(a, 1)
            elif ans == Answer.B and b >= a:
                scores[qq] += 3
            elif ans == Answer.C:
                if a > b:
                    scores[qq] += b * 5 / max(a, 1) / 3 * 2
                else:
                    scores[qq] += 2


class _Q17Scorer(QuestionScorer):
    id = 17

    def score(self, answers, scores):
        a, b, c, d = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                if b == c == d == 0:
                    scores[qq] += 8 / max(a, 1)
            elif ans == Answer.B:
                if c == d == 0:
                    scores[qq] += 8 / max(b, 1) - 1
            elif ans == Answer.C:
                if d == 0:
                    scores[qq] += 8 / max(c, 1) - 2
            elif ans == Answer.D:
                scores[qq] += 8 / max(d, 1) - 3


class _Q18Scorer(QuestionScorer):
    id = 18

    def score(self, answers, scores):
        _, _, c, _ = _count(answers)
        parity = c % 2
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 2 * (1 - parity)
            elif ans == Answer.B:
                scores[qq] += 2 * (parity - 1)
            elif ans == Answer.D:
                scores[qq] += 0.5


class _Q19Scorer(QuestionScorer):
    id = 19

    def score(self, answers, scores):
        for qq, ans in answers.items():
            if ans == Answer.B:
                scores[qq] += random.randint(-2, 2)
            elif ans == Answer.C:
                scores[qq] += random.uniform(-2, 2)


class _Q20Scorer(QuestionScorer):
    id = 20

    def score(self, answers, scores):
        a, b, _, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += 2 - 0.5 * a
            elif ans == Answer.C:
                scores[qq] += 4 - 0.5 * a - b


class _Q21Scorer(QuestionScorer):
    id = 21

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a > 3:
                scores[qq] -= 2
            elif ans == Answer.B and b > 2:
                scores[qq] -= 2
            elif ans == Answer.C:
                scores[qq] += -3 if c > 1 else 2
            elif ans == Answer.D:
                scores[qq] -= 1


class _Q22Scorer(QuestionScorer):
    id = 22

    def score(self, answers, scores):
        _, b, c, d = _count(answers)
        invest = b + c * 2 + d * 3
        if 15 >= invest >= 10:
            outcome = 1
        elif invest > 15:
            outcome = 2
        else:
            outcome = 0
        for qq, ans in answers.items():
            if ans == Answer.A:
                pass
            elif ans == Answer.B:
                if outcome == 1:
                    scores[qq] += 1
                elif outcome == 2:
                    scores[qq] += 3
                else:
                    scores[qq] -= 1
            elif ans == Answer.C:
                if outcome == 1:
                    scores[qq] += 2
                elif outcome == 2:
                    scores[qq] += 2
                else:
                    scores[qq] -= 2
            elif ans == Answer.D:
                if outcome == 1:
                    scores[qq] += 3
                elif outcome == 2:
                    scores[qq] += 1
                else:
                    scores[qq] -= 3


class _Q23Scorer(QuestionScorer):
    id = 23

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a != max(a, b, c) and a != min(a, b, c):
                scores[qq] += 2
            elif ans == Answer.B and b != max(a, b, c) and b != min(a, b, c):
                scores[qq] += 2.5
            elif ans == Answer.C and c != max(a, b, c) and c != min(a, b, c):
                scores[qq] += 3


class _Q24Scorer(QuestionScorer):
    id = 24

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A:
                scores[qq] += 1
            elif ans == Answer.B:
                scores[qq] += 2 if (b * a) % 2 == 0 else -2
            elif ans == Answer.C:
                scores[qq] += 4
                if c >= 3:
                    scores[qq] = 0


class _Q25Scorer(QuestionScorer):
    id = 25

    def score(self, answers, scores):
        a, b, c, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a == min(a, b, c):
                scores[qq] += 5 / max(a, 1)
            elif ans == Answer.B and b != max(a, b, c) and b != min(a, b, c):
                scores[qq] += 6 / max(b, 1)
            elif ans == Answer.C and c == max(a, b, c):
                scores[qq] += 8 / max(c, 1)


class _Q26Scorer(QuestionScorer):
    id = 26

    def score(self, answers, scores):
        a, b, _, _ = _count(answers)
        for qq, ans in answers.items():
            if ans == Answer.A and a <= 2:
                scores[qq] += 2
            elif ans == Answer.B and b >= 4:
                scores[qq] += 2
            elif ans == Answer.C and a > b:
                scores[qq] += 2
            elif ans == Answer.D and b > a:
                scores[qq] += 2


# ---- Registry ----

_SCORER_REGISTRY: dict[int, QuestionScorer] = {}


def _build_registry():
    for cls in QuestionScorer.__subclasses__():
        inst = cls()
        _SCORER_REGISTRY[cls.id] = inst


def get_scorer(qid: int) -> QuestionScorer | None:
    if not _SCORER_REGISTRY:
        _build_registry()
    return _SCORER_REGISTRY.get(qid)


# ---- Helpers ----

def _count(answers: dict[int, Answer]) -> tuple[int, int, int, int]:
    a = b = c = d = 0
    for v in answers.values():
        if v == Answer.A:
            a += 1
        elif v == Answer.B:
            b += 1
        elif v == Answer.C:
            c += 1
        elif v == Answer.D:
            d += 1
    return a, b, c, d


def _int_to_chinese(num: int) -> str:
    digits = "零一二三四五六七八九"
    units = ["", "十", "百", "千"]
    if num == 0:
        return "零"
    result = ""
    unit_pos = 0
    while num > 0:
        digit = num % 10
        if digit != 0:
            result = digits[digit] + units[unit_pos] + result
        elif result and result[0] != digits[0]:
            result = digits[0] + result
        num //= 10
        unit_pos += 1
    if result.startswith("一十"):
        result = result[1:]
    return result


# ---- Question loading ----

_question_cache: dict[int, Question] | None = None


async def load_questions(filepath: str | None = None) -> dict[int, Question]:
    global _question_cache
    if _question_cache is not None:
        return _question_cache

    if filepath is None:
        filepath = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', QUESTION_FILE
        )

    def _sync():
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    content = await asyncio.to_thread(_sync)

    questions: dict[int, Question] = {}
    blocks = content.split('断')
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.match(r'(\d+)', block)
        if not m:
            continue
        qid = int(m.group(1))
        text = block[len(m.group(0)):].strip()
        if text:
            questions[qid] = Question(qid, text)

    _question_cache = questions
    return questions


async def generate_ranking(scores: dict[int, float],
                           names: dict[int, str]) -> str:
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    text = ""
    rank = 1
    prev_score = None
    same: list[int] = []

    for i, (qq, score) in enumerate(sorted_scores):
        if score != prev_score:
            if same:
                names_str = "和".join(names[p] for p in same)
                text += f"第{_int_to_chinese(rank)}名:{names_str}：{prev_score:.2f}分\n"
                rank += len(same)
                same = []
            prev_score = score
        same.append(qq)

    if same:
        names_str = "和".join(names[p] for p in same)
        text += f"第{_int_to_chinese(rank)}名:{names_str}：{prev_score:.2f}分\n"

    return text
