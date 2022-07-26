from typing import Optional, Tuple

from mautrix.types import Format, MessageType, TextMessageEventContent
from mautrix_wechat.user import User
from mautrix_wechat.db.message import Message as DBMessage
from wesdk.types import Message, TxtMessage


async def matrix_to_wechat(msg: TextMessageEventContent, sender: User, show_sender: bool = False) -> Tuple[TextMessageEventContent, str]:
    body = ''
    nick = None
    if event_id := msg.get_reply_to():
        try:
            if db_msg := await DBMessage.get_by_mxid(event_id):
                if nick := await sender.client.get_chatroom_member_nick(db_msg.source, db_msg.sender):
                    nick = nick.nick
        except Exception:
            pass
    if show_sender:
        return body + f"{sender.wxname}@Matrix: {msg.body}", nick
    return body + msg.body, nick
    