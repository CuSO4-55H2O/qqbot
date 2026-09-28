from __future__ import annotations

from helper_fun import get_user_nickname
from bot.plugin import EventHandler, register
from bot.request import Outcome, Poke, Recall, Reply
from constant import *


@register
class EventHandlerPoke(EventHandler):
    name = EventHandlerName.POKE
    priority = 1
    abstract = False

    async def handle_event(self, event: dict) -> Outcome:
        if event['post_type'] == 'notice' and event['notice_type'] == 'notify' \
                and event['sub_type'] == 'poke' \
                and event['target_id'] == self.deps.own_id and 'group_id' in event:
            return Outcome.handled(Poke(qq=int(event['user_id']),
                                        group_id=event['group_id']))
        return Outcome.pass_()


@register
class EventHandlerRevoke(EventHandler):
    name = EventHandlerName.REVOKE
    priority = 2
    abstract = False

    async def handle_event(self, event: dict) -> Outcome:
        if event['post_type'] == 'notice' and event['notice_type'] == 'group_recall':
            return Outcome.handled(Recall(group_id=event['group_id'],
                                          message_id=event['message_id'],
                                          qq=event['user_id']))
        return Outcome.pass_()


@register
class EventHandlerGroupDecrease(EventHandler):
    name = EventHandlerName.GROUP_DECREASE
    priority = 3
    abstract = False

    async def handle_event(self, event: dict) -> Outcome:
        if event['post_type'] == 'notice' and event['notice_type'] == 'group_decrease':
            sub_type = event.get('sub_type')
            user_id = event['user_id']
            group = event['group_id']
            user_nick = await get_user_nickname(user_id)
            if sub_type == 'leave':
                text = f"{user_nick}({user_id}) 主动退群了"
            elif sub_type == 'kick':
                operator_id = event.get('operator_id', user_id)
                if operator_id and operator_id != 0:
                    operator_nick = await get_user_nickname(operator_id)
                else:
                    operator_nick = "管理员"
                text = f"{user_nick}({user_id}) 被 {operator_nick}({operator_id}) 踢出了群聊"
            else:
                text = f"{user_nick}({user_id}) 退群了（原因：{sub_type}）"

            return Outcome.handled(Reply(msg=text, msg_type=Name.GROUP, number=group))
        return Outcome.pass_()
