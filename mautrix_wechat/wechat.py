import asyncio
import logging
from typing import Optional, List, TYPE_CHECKING
from venv import create
from mautrix.bridge import portal

# from mausignald import SignaldClient
# from mausignald.types import (Message, MessageData, Receipt, TypingNotification, OwnReadReceipt,
#                               Address, ReceiptType)
from mautrix.util.logging import TraceLogger

from mautrix_wechat.db import Message as DBMessage
from mautrix_wechat import user as u, portal as po, puppet as pu
from wesdk.client import WechatClient
from wesdk.types import PicMessage, TxtMessage, TxtCiteMessage, WechatID, WechatUser

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class WechatHandler(WechatClient):
    log: TraceLogger = logging.getLogger("mau.wechat")
    loop: asyncio.AbstractEventLoop
    user: Optional[u.User]

    def __init__(self, ip: str, port: int, bridge: "WechatBridge") -> None:
        self.log = self.log.getChild(f"{ip}:{port}")
        super().__init__(ip, port, self.log, bridge.loop)
        self.user = None

    async def start(self) -> None:
        await self.connect()

    async def stop(self) -> None:
        await self.disconnect()

    async def on_personal_info(self, source: Optional[WechatUser]) -> None:
        if not source:
            self.log.warning("No personal info found, try again in 5 seconds...")
            await asyncio.sleep(5)
            self.get_personal_info()
            return

        try:
            user = await u.User.get_by_wxid(source.wxid)
            if not user:
                self.log.debug(f"Creating user for {source.wxid}")
                user = u.User(
                    pu.Puppet.get_mxid_from_wxid(source.wxid),
                    source.wxid,
                    source.name,
                    source.wxcode,
                )
                await user.insert()
                user._postinit()
                self.log.debug(f"Created user for {source.wxid}")
            user.login_complete(self)
            self.user = user
            self.get_user_list()
        except Exception:
            self.log.exception("Error handling personal info", exc_info=True)

    async def on_user_list(self, users: list[WechatUser]) -> None:
        for user in users:
            if user.wxid.endswith('chatroom'):
                portal = await po.Portal.get_by_wxid(user.wxid, self.wx_id)
                if not portal:
                    try:
                        portal = po.Portal(user.wxid, receiver=self.wx_id, name=user.name)
                        await portal.insert()
                        portal._postinit()
                        self.log.debug(f"Created portal for {user.name} {user.wxid}")
                    except Exception:
                        self.log.exception(f"Fail to create portal for {user.name} {user.wxid}")
                else:
                    try:
                        portal: po.Portal
                        portal.name = user.name
                        await portal.save()
                    except Exception:
                        self.log.exception(f"Fail to update portal for {user.name} {user.wxid}")
            else:
                puppet = await pu.Puppet.get_by_wxid(user.wxid)
                if not puppet:
                    try:
                        puppet = pu.Puppet(user.wxid, user.headimg, user.name, user.remarks, user.wxcode)
                        await puppet.insert()
                        self.log.debug(f"Created puppet for {user.name} {user.wxid}")
                    except Exception:
                        self.log.exception(f"Fail to create puppet for {user.name} {user.wxid}")
                else:
                    try:
                        puppet: pu.Puppet
                        puppet.headimg = user.headimg
                        puppet.name = user.name
                        puppet.remarks = user.remarks
                        puppet.wxcode = user.wxcode
                        await puppet.save()
                    except Exception:
                        self.log.exception(f"Fail to update puppet for {user.name} {user.wxid}")

    async def on_txt_message(self, msg: TxtMessage) -> None:
        print(f"Received txt message: {msg}")
        try:
            sender: pu.Puppet = await pu.Puppet.get_by_wxid(msg.user, create=True)
            portal: po.Portal = await po.Portal.get_by_wxid(msg.source, create=True)
            await portal.handle_txt_message(self.user, sender, msg)
        except Exception:
            self.log.exception("Error handling txt message", exc_info=True)

    async def on_pic_message(self, msg: PicMessage) -> None:
        print(f"Received pic message: {msg}")

    async def on_txt_cite_message(self, msg: TxtCiteMessage) -> None:
        print(f"Received txt cite message: {msg}")
