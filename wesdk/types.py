from typing import Optional
from datetime import datetime
from dataclasses import dataclass, field


class WechatID(str):
    @property
    def is_chatroom(self):
        return self.endswith('chatroom')


@dataclass
class WechatUser:
    headimg: str
    name: str
    remarks: str
    wxcode: str
    wxid: WechatID
    chat_room_members: list[WechatID] = field(default_factory=list)

    @property
    def is_chatroom(self):
        return self.wxid.is_chatroom

@dataclass
class WechatUserDetail:
    big_headimg: str
    cover: str
    little_headimg: str
    signature: str

@dataclass
class ChatRoomNick:
    wxid: WechatID
    roomid: WechatID
    nick: str

@dataclass
class Message:
    id: str
    source: WechatID
    sender: WechatID
    time: datetime

@dataclass
class TxtMessage(Message):
    content: str

@dataclass
class PicMessage(Message):
    msg: Optional[str]
    path: Optional[str]

@dataclass
class TxtCiteMessage(Message):
    # TODO: parse xml
    content: str