from pathlib import Path
from mautrix.appservice.api.intent import IntentAPI
from mautrix.types import (
    Format,
    MessageType,
    TextMessageEventContent,
    MessageEventContent,
    MediaMessageEventContent,
)

from mautrix_wechat import portal as po
from mautrix_wechat.util.file import upload_file
from wesdk.types import Message, PicMessage, TxtCiteMessage, TxtMessage


async def wechat_to_matrix(msg: Message, portal: "po.Portal") -> MessageEventContent:
    if isinstance(msg, TxtMessage):
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    elif isinstance(msg, PicMessage):
        msg: PicMessage
        if f := Path(msg.path).exists():
            try:
                with open(msg.path, "rb") as f:
                    data = f.read()
                mxc_url = await upload_file(
                    data,
                    portal.main_intent,
                    portal.config
                )
                return MediaMessageEventContent(
                    msgtype=MessageType.IMAGE,
                    url=mxc_url)
            except Exception as e:
                # TODO: maybe should throw 
                return TextMessageEventContent(msgtype=MessageType.TEXT, body=e)
        elif msg.msg:
            return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.msg)
        else:
            return TextMessageEventContent(msgtype=MessageType.TEXT, body=f"Image not found: {msg.path}")
    elif isinstance(msg, TxtCiteMessage):
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    return TextMessageEventContent(msgtype=MessageType.TEXT, body=str(msg))
