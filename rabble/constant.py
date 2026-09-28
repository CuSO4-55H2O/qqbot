from enum import IntEnum


class Answer(IntEnum):
    """Player answer choices — used everywhere instead of magic 0/1/2/3."""
    A = 0
    B = 1
    C = 2
    D = 3


# ---- Answer constants ----

ALLOWED_ABC: tuple[str, ...] = ('A', 'B', 'C')
ALLOWED_ABCD: tuple[str, ...] = ('A', 'B', 'C', 'D')

ANSWER_MAP: dict[str, Answer] = {
    'a': Answer.A, 'A': Answer.A,
    'b': Answer.B, 'B': Answer.B,
    'c': Answer.C, 'C': Answer.C,
    'd': Answer.D, 'D': Answer.D,
}
ANSWER_CHAR: dict[Answer, str] = {
    Answer.A: 'A',
    Answer.B: 'B',
    Answer.C: 'C',
    Answer.D: 'D',
}


# ---- Game configuration ----

DEFAULT_TURN: int = 9
QUESTION_FILE: str = '乌合之众.txt'


# ---- Commands ----

CMD_JOIN: str = '加入乌合之众'
CMD_LEAVE: str = '退出乌合之众'
CMD_START: str = '开始乌合之众'
CMD_REMIND: str = '提醒'
CMD_BLIND: str = '盲选'
