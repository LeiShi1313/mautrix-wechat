from mautrix.types import Format, MessageType, TextMessageEventContent
from wesdk.types import Message, TxtMessage

async def wechat_to_matrix(msg: Message) -> TextMessageEventContent:
    if isinstance(msg, TxtMessage):
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    