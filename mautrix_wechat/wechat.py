import asyncio
import logging
from typing import Optional, List, TYPE_CHECKING, Tuple
from venv import create
from mautrix.bridge import portal

# from mausignald import SignaldClient
# from mausignald.types import (Message, MessageData, Receipt, TypingNotification, OwnReadReceipt,
#                               Address, ReceiptType)
from mautrix.util.logging import TraceLogger

from mautrix_wechat.db import Message as DBMessage
from mautrix_wechat import user as u, portal as po, puppet as pu
from wesdk.client import WechatClient
from wesdk.types import Message, PicMessage, TxtMessage, TxtCiteMessage, WechatID, WechatUser

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class WechatHandler(WechatClient):
    log: TraceLogger = logging.getLogger("mau.wechat")
    loop: asyncio.AbstractEventLoop
    user: Optional[u.User]

    def __init__(self, ip: str, port: int, admin: str, bridge: "WechatBridge") -> None:
        self.admin = admin
        self.log = self.log.getChild(f"{ip}:{port}")
        super().__init__(ip, port, self.log, bridge.loop)
        self.user = None

    async def start(self) -> None:
        await self.connect()
        fetched = await self.fetch_personal_info()
        if fetched:
            await self.fetch_contact_list()

    async def stop(self) -> None:
        await self.disconnect()

    async def fetch_personal_info(self) -> bool:
        info = await self.get_personal_info()
        if not info:
            # TODO: this will actually block the start action?
            self.log.warning("No personal info found, try again in 5 seconds...")
            await asyncio.sleep(5)
            return self.fetch_personal_info()

        try:
            user = await u.User.get_by_wxid(info.wxid)
            if not user:
                self.log.debug(f"Creating user for {info.wxid}")
                user = u.User(
                    self.admin,
                    info.wxid,
                    info.name,
                    info.wxcode,
                )
                await user.insert()
                user._postinit()
                self.log.debug(f"Created user for {info.wxid}")
            else:
                user.mxid = self.admin
                user.name = info.name
                user.wxcode = info.wxcode
                await user.save()
            user.login_complete(self)
            self.user = user
        except Exception:
            self.log.exception("Error handling personal info", exc_info=True)
            return False
        return True

    async def fetch_contact_list(self) -> None:
        users = await self.get_contact_list()
        await self.fetch_chatroom_members()
        for user in users:
            if user.wxid.endswith("chatroom"):
                portal = await po.Portal.get_by_wxid(user.wxid, self.wx_id)
                if not portal:
                    try:
                        portal = po.Portal(
                            user.wxid, receiver=self.wx_id, name=user.name
                        )
                        await portal.insert()
                        await portal._postinit()
                        self.log.debug(f"Created portal for {user.name} {user.wxid}")
                    except Exception:
                        self.log.exception(
                            f"Fail to create portal for {user.name} {user.wxid}"
                        )
                else:
                    try:
                        portal: po.Portal
                        portal.name = user.name
                        await portal.save()
                    except Exception:
                        self.log.exception(
                            f"Fail to update portal for {user.name} {user.wxid}"
                        )
                if portal.mxid:
                    await portal.update_matrix_room(self.user, user)
            else:
                puppet = await pu.Puppet.get_by_wxid(user.wxid)
                if not puppet:
                    try:
                        puppet = pu.Puppet(
                            user.wxid,
                            user.headimg,
                            user.name,
                            user.remarks,
                            user.wxcode,
                        )
                        await puppet.insert()
                        puppet._postinit()
                        self.log.debug(f"Created puppet for {user.name} {user.wxid}")
                    except Exception:
                        self.log.exception(
                            f"Fail to create puppet for {user.name} {user.wxid}"
                        )
                else:
                    try:
                        puppet: pu.Puppet
                        puppet.headimg = user.headimg
                        puppet.name = user.name
                        puppet.remarks = user.remarks
                        puppet.wxcode = user.wxcode
                        await puppet.save()
                    except Exception:
                        self.log.exception(
                            f"Fail to update puppet for {user.name} {user.wxid}"
                        )

    async def get_msg_info(self, msg: Message) -> Tuple["pu.Puppet", "po.Portal"]:
        sender: pu.Puppet = await pu.Puppet.get_by_wxid(msg.sender, create=True)
        portal: po.Portal = await po.Portal.get_by_wxid(
            msg.source, self.wx_id, create=True
        )
        return sender, portal

    async def on_txt_message(self, msg: TxtMessage) -> None:
        print(f"Received txt message: {msg}")
        sender, portal = await self.get_msg_info(msg)

        try:
            await sender.update_info(
                self._contact_list.get(msg.sender),
                await self.get_personal_detail(msg.sender),
                await self.get_user_nick(msg.sender),
            )
        except Exception:
            self.log.exception("Error updating puppet info", exc_info=True)

        try:
            await portal.handle_message(self.user, sender, msg, self._contact_list.get(msg.source))
            if portal.mxid:
                await portal.update_info(self.user, self._contact_list.get(msg.source))
        except Exception:
            self.log.exception("Error handling txt message", exc_info=True)

    async def on_at_message(self, msg: TxtMessage) -> None:
        print(f"Received at message: {msg}")

    async def on_pic_message(self, msg: PicMessage) -> None:
        print(f"Received pic message: {msg}")

    async def on_txt_cite_message(self, msg: TxtCiteMessage) -> None:
        print(f"Received txt cite message: {msg}")
