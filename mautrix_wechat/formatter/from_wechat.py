import struct
from pathlib import Path
from mautrix.appservice.api.intent import IntentAPI
from mautrix.types import (
    Format,
    MessageType,
    TextMessageEventContent,
    MessageEventContent,
    MediaMessageEventContent,
)

from lxml import etree
from mautrix_wechat import portal as po
from mautrix_wechat.util.file import upload_file

from mautrix_wechat.db.message import Message as DBMessage
from wesdk.types import Message, PicMessage, TxtCiteMessage, TxtMessage

def add_surrogate(text):
    return ''.join(
        # SMP -> Surrogate Pairs (Telegram offsets are calculated with these).
        # See https://en.wikipedia.org/wiki/Plane_(Unicode)#Overview for more.
        ''.join(chr(y) for y in struct.unpack('<HH', x.encode('utf-16le')))
        if (0x10000 <= ord(x) <= 0x10FFFF) else x for x in text
    )


def del_surrogate(text):
    return text.encode('utf-16', 'surrogatepass').decode('utf-16')


async def wechat_to_matrix(msg: Message, portal: "po.Portal") -> MessageEventContent:
    if isinstance(msg, TxtMessage):
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    elif isinstance(msg, PicMessage):
        msg: PicMessage
        if msg.path and Path(msg.path).exists():
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
        root = etree.fromstring(msg.content)
        content = TextMessageEventContent(msgtype=MessageType.TEXT)
        t = root.find("*//type")
        if t.text == '57':
            body = ''
            formatted_body = '<blockquote>'
            if refermsg := root.find("*//refermsg"):
                if displayname := refermsg.find("./displayname").text.strip():
                    # TODO: replace with real matrix user
                    body += f"> **{displayname} (WeChat)**\n"
                    formatted_body += f"<b>{displayname} (WeChat)</b><br />"
                refertype = refermsg.find("./type").text
                if refertype == '1':
                    if refercontent := refermsg.find("./content").text.strip():
                        body += f"> {refercontent}\n"
                        formatted_body += f"{refercontent}"
                elif refertype == '49':
                    if refercontent := etree.fromstring(refermsg.find("./content").text).find("*//title").text.strip():
                        body += f"> {refercontent}\n"
                        formatted_body += f"{refercontent}"
            body += f"{root.find('*//title').text}"
            formatted_body += f"</blockquote><br />{root.find('*//title').text}"
            content.body = body
            content.ensure_has_html()
            content.formatted_body = formatted_body
            return content
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    return TextMessageEventContent(msgtype=MessageType.TEXT, body=str(msg))
