"""一次请求的输入与输出形状。

`Request` 是 frozen 的 —— 功能改不动它，想发东西只能返回 `Outcome`。
这一条约束就是全部目的：从前 `Context` 同时装着「问题」和「答案」，
所以功能必须手写「设 flag → 攒 text → 末尾 reply」的三段式，而那段样板里
嵌着一个顺序陷阱（`reply` 只在 flag 已置位时才真发），已经造成过丢消息。

`Reply` 只管「一段文本」。会碰 NapCat 但不属于文本回复的动作（贴表情、戳一戳、
撤回、原样合并转发）是另外几个类型 —— 它们同样是**数据**，由 BotCore 统一执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from constant import Name


@dataclass(frozen=True)
class Request:
    """一条入站消息：事件事实 + 本机身份 + 解析好的策略快照。"""

    # 事件事实
    qq: int
    group_id: int
    msg: str
    msg_type: str
    nickname: str
    message_id: int

    # 本机身份。原先不在上下文里，需要知道自己是谁的功能只能靠构造参数拿 ——
    # FeatureRoulette(bot_user_id=...)、FeatureChatRAG(bot_nickname=...) 就是这么来的。
    own_id: int
    own_nickname: str

    # 策略快照（派发时解析一次，功能只读）
    options: Mapping[str, int]
    admin: tuple[int, ...]
    blacklist: tuple[int, ...]
    super_admin: int

    @property
    def is_group(self) -> bool:
        return self.msg_type == Name.GROUP


@dataclass(frozen=True)
class Reply:
    """一条待发消息。取代原先裸 dict（{'msg_type','number','msg'}）。

    裸 dict 的 key 写错要到 output.send_msg 里才 KeyError，再被发送循环的
    try 吞掉 —— 消息静默消失、日志里只剩一行 print。换成类型后是 AttributeError。
    """

    msg: str
    msg_type: str
    number: int
    # 发出这条之前先等这么久。只用在「一次连发很多条」的记录功能上
    # （NapCat 对连发有节流），其它地方一律 0。
    gap: float = 0.0

    @staticmethod
    def same_conversation(req: Request, text: str) -> "Reply":
        """回到这条消息来的那个会话（群消息回群，私聊回本人）。"""
        target = req.group_id if req.is_group else req.qq
        return Reply(msg=text, msg_type=req.msg_type, number=target)

    def as_dict(self) -> dict[str, Any]:
        return {"msg_type": self.msg_type, "number": self.number, "msg": self.msg}


@dataclass(frozen=True)
class Forward:
    """原样合并转发，`nodes` 已经是 NapCat 的 node 结构。

    它不能被 Reply 代替：记录功能的每个节点署名是**那条记录的原作者**，
    而走 send_msg 会被 custom_split 统一改写成机器人自己。
    """

    nodes: tuple[dict[str, Any], ...]
    number: int
    gap: float = 0.0


@dataclass(frozen=True)
class EmojiLike:
    """给某条消息贴表情回应。"""

    message_id: int
    emoji_id: str


@dataclass(frozen=True)
class Poke:
    qq: int
    group_id: int


@dataclass(frozen=True)
class Recall:
    group_id: int
    message_id: int
    qq: int


# BotCore 执行的东西。功能只能通过返回它来产生副作用，自己不许碰 output。
Outbound = Reply | Forward | EmojiLike | Poke | Recall


@dataclass(frozen=True)
class Outcome:
    """一条消息处理完的结论：接住了吗、要发什么。"""

    consumed: bool
    actions: tuple[Outbound, ...] = ()

    @staticmethod
    def pass_() -> "Outcome":
        """没接住，交给下一个功能。"""
        return Outcome(consumed=False)

    @staticmethod
    def handled(*actions: Outbound) -> "Outcome":
        """接住并发出这些。"""
        return Outcome(consumed=True, actions=tuple(actions))

    @staticmethod
    def silent() -> "Outcome":
        """接住但什么都不发（如入闸丢弃）。

        与 handled() 的区别只在 actions 为空，但语义必须分明：consumed=True
        意味着这条消息不进语料库。
        """
        return Outcome(consumed=True)
