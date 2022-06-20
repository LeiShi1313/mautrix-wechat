from typing import (
    Optional,
    Dict,
    Tuple,
    AsyncIterable,
    Awaitable,
    AsyncGenerator,
    Union,
    TYPE_CHECKING,
    cast,
)
from uuid import UUID
import asyncio
from datetime import datetime
from collections import deque

# from mausignald.types import Address, Contact, Profile
from mautrix.bridge import BasePortal
from mautrix.appservice import AppService, IntentAPI
from mautrix.types import UserID, SyncToken, RoomID
from mautrix.util.simple_template import SimpleTemplate

from mautrix_wechat.db import Portal as DBPortal, Message as DBMessage
from mautrix_wechat.config import Config
from mautrix_wechat import (
    user as u,
    puppet as p,
    portal as po,
    matrix as m,
    wechat as w,
)
from wesdk.types import TxtMessage, WechatID

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class Portal(DBPortal, BasePortal):
    by_mxid: Dict[RoomID, "Portal"] = {}
    by_wxid: Dict[Tuple[WechatID, WechatID], "Portal"] = {}
    config: Config
    matrix: "m.MatrixHandler"
    signal: "w.WechatHandler"
    az: AppService
    private_chat_portal_meta: bool

    _main_intent: Optional[IntentAPI]
    _msg_dedup: deque[tuple[WechatID, WechatID, str, datetime]]

    @classmethod
    def init_cls(cls, bridge: "WechatBridge") -> None:
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.wechat = bridge.wechat
        cls.az = bridge.az
        cls.loop = bridge.loop
        BasePortal.bridge = bridge

    def __init__(
        self,
        wxid: WechatID,
        mxid: Optional[RoomID],
        name: Optional[str],
        encrypted: bool,
    ) -> None:
        super().__init__(wxid=wxid, mxid=mxid, name=name, encrypted=encrypted)
        BasePortal.__init__(self)
        self.log = self.log.getChild(self.wxid)
        self._main_intent = None
        self._msg_dedup = deque(maxlen=100)

    async def _postinit(self) -> None:
        self.by_wxid[(self.wxid, self.receiver)] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self
        if self.is_direct:
            puppet = await p.Puppet.get_by_mxid(self.mxid)
            self._main_intent = puppet.default_mxid_intent
        elif not self.is_direct:
            self._main_intent = self.az.intent

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError("Portal must be _postinit()ed before main_intent can be used")
        return self._main_intent

    @classmethod
    async def get_by_wxid(
        cls, wxid: WechatID, create: bool = False
    ) -> Optional["Portal"]:
        portal = cast(cls, await super().get_by_wxid(wxid))
        if portal is not None:
            await portal._postinit()
            return portal

        if create:
            portal = cls(wxid)
            await portal.insert()
            await portal._postinit()
            return portal

        return None

    async def handle_txt_message(self, msg: TxtMessage) -> None:
        if (msg.source, msg.user, msg.content, msg.time) in self._msg_dedup:
            self.log.debug(
                f"Ignoring message {msg.content} by {msg.user} in {msg.source} at {msg.time} as it was already handled"
            )
            return
        self._msg_dedup.appendleft((msg.source, msg.user, msg.content, msg.time))

        if await DBMessage.get_by_wechat_id(
            msg.user, msg.source, self.wxid, msg.time.timestamp()
        ):
            self.log.debug(
                f"Ignoring message {msg.content} by {msg.user} in {msg.source} at {msg.time} as it was already handled"
            )
            return
        self.log.debug(f"Start handling message by {msg.user} in {msg.source} at {msg.time}")
        self.log.trace(f"Message content: {msg.content}")


    @classmethod
    async def all(cls) -> AsyncIterable['Portal']:
        portal: 'Portal'
        for portal in await super().all():
            try:
                yield cls.by_wxid[(portal.wxid, portal.receiver)]
            except KeyError:
                await portal._postinit()
                yield portal