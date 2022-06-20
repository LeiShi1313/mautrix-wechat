import asyncio
import logging
from typing import Optional, List, TYPE_CHECKING

# from mausignald import SignaldClient
# from mausignald.types import (Message, MessageData, Receipt, TypingNotification, OwnReadReceipt,
#                               Address, ReceiptType)
from mautrix.util.logging import TraceLogger

from mautrix_wechat.db import Message as DBMessage
from mautrix_wechat import user as u, portal as po, puppet as pu
from wesdk.client import WechatClient
from wesdk.types import PicMessage, TxtMessage, TxtCiteMessage

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class WechatHandler(WechatClient):
    log: TraceLogger = logging.getLogger("mau.wechat")
    loop: asyncio.AbstractEventLoop

    def __init__(self, bridge: "WechatBridge") -> None:
        super().__init__(
            bridge.config["wechat.wechat_box_ip"],
            bridge.config["wechat.wechat_box_port"],
            self.log,
            bridge.loop,
        )

    async def start(self) -> None:
        await self.connect()

    async def stop(self) -> None:
        await self.disconnect()

    async def on_txt_message(self, msg: TxtMessage) -> None:
        print(f"Received txt message: {msg}")
        # sender = await pu.Puppet.get_by_wxid(msg.user)
        # receiver = await u.User.get
        # portal = po.Portal.get_by_wxid(msg.source)
        # await portal.handle_txt_message(msg)

    async def on_pic_message(self, msg: PicMessage) -> None:
        print(f"Received pic message: {msg}")

    async def on_txt_cite_message(self, msg: TxtCiteMessage) -> None:
        print(f"Received txt cite message: {msg}")
