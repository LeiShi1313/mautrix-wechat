from typing import NewType
from datetime import datetime
from dataclasses import dataclass


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
    user: WechatID
    time: datetime

@dataclass
class TxtMessage(Message):
    content: str

@dataclass
class PicMessage(Message):
    # TODO: decrypt pic message
    content: str

@dataclass
class TxtCiteMessage(Message):
    # TODO: parse xml
    content: str