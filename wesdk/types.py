from typing import NewType
from datetime import datetime
from dataclasses import dataclass


WechatID = NewType('WechatID', str)

@dataclass
class WechatUser:
    headimg: str
    name: str
    remarks: str
    wxcode: str
    wxid: WechatID


@dataclass
class Message:
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