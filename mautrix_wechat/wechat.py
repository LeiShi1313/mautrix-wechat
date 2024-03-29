import asyncio
from datetime import datetime
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
from wesdk.types import (
    Message,
    PicMessage,
    TxtMessage,
    TxtCiteMessage,
    WechatID,
    WechatUser,
)

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class WechatHandler(WechatClient):
    log: TraceLogger = logging.getLogger("mau.wechat")
    loop: asyncio.AbstractEventLoop
    user: Optional[u.User]

    def __init__(
        self,
        ip: str,
        port: int,
        admin: str,
        bridge: "WechatBridge",
        can_relay: bool = False,
        show_sender: bool = True,
    ) -> None:
        self.admin = admin
        self.log = self.log.getChild(f"{ip}:{port}")
        super().__init__(ip, port, self.log, bridge.loop)
        self.user = None
        self.can_relay = can_relay
        self.show_sender = show_sender

    async def start(self) -> None:
        await self.connect()
        self.loop.create_task(self._fetch_info())

    async def manual_start(self, wxid: str, wxcode: str, wxname: str) -> None:
        await self.connect()
        self.manual_login(wxid, wxcode, wxname)
        if await self._set_user_info(
            WechatUser(headimg="", name=wxname, remarks="", wxcode=wxcode, wxid=wxid)
        ):
            self.loop.create_task(self._fetch_info(manual=True))

    async def stop(self) -> None:
        await self.disconnect()

    async def _fetch_info(self, manual: bool = False) -> None:
        try:
            if manual or await self.fetch_personal_info():
                await self.fetch_contact_list()
        except asyncio.TimeoutError as e:
            self.logger.info("Fetch info timeout, trying again in 5 seconds...")
            await asyncio.sleep(5)
            return await self._fetch_info(manual)

    async def fetch_personal_info(self) -> bool:
        info = await self.get_personal_info()
        if not info:
            # TODO: this will actually block the start action?
            self.log.warning("No personal info found, try again in 5 seconds...")
            await asyncio.sleep(5)
            return await self.fetch_personal_info()
        return await self._set_user_info(info)

    async def _set_user_info(self, info: WechatUser) -> bool:
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
        try:
            await self.fetch_chatroom_members()
        except asyncio.exceptions.TimeoutError:
            pass
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
                        if self.can_relay:
                            await portal.set_relay_user(self.user)
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
                    if self.can_relay:
                        await portal.set_relay_user(self.user)
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
                        # TODO: saved twice here
                        await puppet.update_info(wechat_user=user)
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

    async def on_heart_beat_timeout(self) -> None:
        self.log.error(f"Heart beat timeout, last hear beat: {self.last_heart_beat}")

    async def on_txt_message(self, msg: TxtMessage) -> None:
        self.log.trace(f"Received txt message: {msg}")
        return await self.handle_message(msg)

    async def on_at_message(self, msg: TxtMessage) -> None:
        self.log.trace(f"Received at message: {msg}")
        # return await self.handle_message(msg)

    async def on_pic_message(self, msg: PicMessage) -> None:
        self.log.trace(f"Received pic message: {msg}")
        return await self.handle_message(msg)

    async def on_txt_cite_message(self, msg: TxtCiteMessage) -> None:
        self.log.trace(f"Received txt cite message: {msg}")
        return await self.handle_message(msg)

    async def handle_message(self, msg: Message) -> None:
        try:
            self.log.info("hi, I'm here")
            sender, portal = await self.get_msg_info(msg)
            self.log.info("hihi, I'm here")
        except Exception as e:
            self.log.exception(f"Error handling message: {msg}", exc_info=True)
            return

        try:
            await sender.update_info(
                self._contact_list.get(msg.sender),
                await self.get_personal_detail(msg.sender),
                await self.get_user_nick(msg.sender),
            )
        except Exception:
            self.log.exception("Error updating puppet info", exc_info=True)

        try:
            await portal.handle_message(
                self.user, sender, msg, self._contact_list.get(msg.source)
            )
            if portal.mxid and msg.source in self._contact_list:
                await portal.update_info(self.user, self._contact_list.get(msg.source))
        except Exception:
            self.log.exception(f"Error handling message: {msg}", exc_info=True)
