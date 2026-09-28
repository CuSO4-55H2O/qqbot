"""自动记录群聊：没被任何功能消费的自然聊天进语料库。

它是 AfterHook 而不是 Feature —— 它不认任何触发词，只是对「整轮功能链的结果」做观察。
原先这段逻辑内联在 BotCore.handle 里，靠一个没有任何插件类的 FeatureName.CHAT_RECORD
开关控制，所以它出现在用户可见的功能列表和管理命令里，却不是插件。

开关仍然是 options.txt 里的 chat_record（用户可见名「聊天记录」），行为不变。
"""

from __future__ import annotations

from bot.plugin import AfterHook, register
from bot.request import Outcome, Request
from constant import DELIMITER, FeatureName
import chat_rag


@register
class AfterHookChatRecord(AfterHook):
    name = FeatureName.CHAT_RECORD
    priority = 100
    abstract = False

    async def after(self, req: Request, outcome: Outcome) -> None:
        """只记录未被任何 feature 消费、也没有回应的自然群聊。"""
        if not req.is_group or outcome.consumed or outcome.actions:
            return
        if req.qq in req.blacklist or DELIMITER in req.msg:
            return
        try:
            await chat_rag.record_chat(req.group_id, req.qq, req.nickname, req.msg)
        except Exception as e:      # noqa: BLE001
            print(f"!!! 聊天记录写入失败 !!!\n{e}")
