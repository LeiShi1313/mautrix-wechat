import struct
from typing import Dict
from html import escape
from textwrap import dedent
from pathlib import Path
from mautrix.appservice.api.intent import IntentAPI
from mautrix.types import (
    EventID,
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
    return "".join(
        # SMP -> Surrogate Pairs (Telegram offsets are calculated with these).
        # See https://en.wikipedia.org/wiki/Plane_(Unicode)#Overview for more.
        "".join(chr(y) for y in struct.unpack("<HH", x.encode("utf-16le")))
        if (0x10000 <= ord(x) <= 0x10FFFF)
        else x
        for x in text
    )


def del_surrogate(text):
    return text.encode("utf-16", "surrogatepass").decode("utf-16")


async def wechat_to_matrix(msg: Message, portal: "po.Portal", msg_cache: Dict[str, EventID] = None) -> MessageEventContent:
    if isinstance(msg, TxtMessage):
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    elif isinstance(msg, PicMessage):
        msg: PicMessage
        if msg.path and Path(msg.path).exists():
            try:
                with open(msg.path, "rb") as f:
                    data = f.read()
                mxc_url = await upload_file(data, portal.main_intent, portal.config)
                return MediaMessageEventContent(msgtype=MessageType.IMAGE, url=mxc_url)
            except Exception as e:
                # TODO: maybe should throw
                return TextMessageEventContent(msgtype=MessageType.TEXT, body=e)
        elif msg.msg:
            return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.msg)
        else:
            return TextMessageEventContent(
                msgtype=MessageType.TEXT, body=f"Image not found: {msg.path}"
            )
    elif isinstance(msg, TxtCiteMessage):
        root = etree.fromstring(msg.content)
        content = TextMessageEventContent(msgtype=MessageType.TEXT)
        t = root.find("*//type")
        # 公众号转载消息
        if t.text == "5":
            title = escape(root.find("*//title").text.strip())
            description = escape(root.find("*//des").text.strip())
            url = escape(root.find("*//url").text.strip())
            # TODO: sourcename is just the chat group, should be appinfo/appname
            if sourceusername := root.find("*//sourceusername"):
                sourceusername = escape(sourceusername.text.strip())
            if sourcedisplayname := root.find("*//sourcedisplayname"):
                sourcedisplayname = escape(sourcedisplayname.text.strip())
            if (appname := root.find("*//appinfo/appname")) is not None:
                appname = escape(appname.text.strip())
            content.body = dedent(
                f"From channel **{sourcedisplayname if sourcedisplayname else (appname if appname else msg.source)}**"
                f"> [**{title}**]({url})\n"
                f"> {description}"
            )
            content.ensure_has_html()
            content.formatted_body = dedent(
                    f"From channel <b>{sourcedisplayname if sourcedisplayname else msg.source}</b><br />"
                    f"<blockquote><a href={url}>{title}</a><br />"
                    f"<p>{description}</p></blockquote>"
                )
            return content
        # Personal chat history 
        elif t.text == '19':
            recorditem = root.find("*//recorditem")
            content.ensure_has_html()
            content.body += 'Forwarded chat history\n'
            content.formatted_body += 'Forwarded chat history<br><blockquote>'
            if recorditem is not None:
                recorditem = etree.fromstring(recorditem.text)
                for item in recorditem.findall('./datalist/dataitem'):
                    sourcetime = item.find('./sourcetime')
                    datadesc = item.find('./datadesc')
                    sourcename = item.find('./sourcename')
                    displayname = f"{sourcename.text.strip() + ' (WeChat)'}"
                    content.body += f"> **{displayname}**: {datadesc.text.strip()}\n"
                    content.formatted_body += f"<b>{displayname}</b>:&nbsp{datadesc.text.strip()}<br />"
            content.formatted_body += '</blockquote>'
            return content
        # Group chat history
        elif t.text == '40':
            title = root.find("*//title")
            description = root.find("*//des")
            content.ensure_has_html()
            content.body += f'**{title.text.strip()}**\n'
            content.formatted_body += f'<b>{title.text.strip()}</b><br><blockquote>'
            for line in description.text.strip().split('\n'):
                content.body += f"> {line}\n"
                content.formatted_body += f"{line}<br />"
            content.formatted_body += '</blockquote>'
            return content
        # Quote message
        elif t.text == "57":
            title = root.find('*//title').text.strip()
            body = ""
            formatted_body = "<blockquote>"
            refermsg = root.find("*//refermsg")
            event_id = None
            if refermsg is not None:
                if (sender := refermsg.find('./chatusr')) is not None:
                    sender = sender.text.strip()
                if (source := refermsg.find('./fromusr')) is not None:
                    source = source.text.strip()
                if (displayname := refermsg.find("./displayname")) is not None:
                    displayname = displayname.text.strip()
                    # TODO: replace with real matrix user
                    body += f"> **{displayname} (WeChat)**\n"
                    formatted_body += f"<b>{displayname} (WeChat)</b><br />"
                
                if (refertype := refermsg.find('./type')) is not None:
                    refertype = refertype.text
                refercontent = None
                if refertype == "1":
                    if refercontent := refermsg.find("./content").text.strip():
                        body += f"> {refercontent}\n"
                        formatted_body += f"{refercontent}"
                elif refertype == "49":
                    if (
                        refercontent := etree.fromstring(
                            refermsg.find("./content").text
                        )
                        .find("*//title")
                        .text.strip()
                    ):
                        body += f"> {refercontent}\n"
                        formatted_body += f"{refercontent}"
                if msg_cache and (event_id := msg_cache.get((sender, source, refercontent))):
                    content.formatted_body = ''
                    content.set_reply(event_id)
            body += f"{title}"
            formatted_body += f"</blockquote><br />{title}"
            if event_id:
                content.body = title
                content.ensure_has_html()
            else:
                content.body = body
                content.ensure_has_html()
                content.formatted_body = formatted_body
            return content
        return TextMessageEventContent(msgtype=MessageType.TEXT, body=msg.content)
    return TextMessageEventContent(msgtype=MessageType.TEXT, body=str(msg))
