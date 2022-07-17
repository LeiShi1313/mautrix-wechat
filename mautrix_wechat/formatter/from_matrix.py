from mautrix.types import Format, MessageType, TextMessageEventContent
from wesdk.types import Message, TxtMessage

async def matrix_to_wechat(msg: TextMessageEventContent) -> TextMessageEventContent:
    return msg.body
    