import logging
from pydoc import cli
from typing import TYPE_CHECKING, AsyncGenerator, Optional, cast, AsyncIterable, Awaitable
from asyncio.tasks import sleep
from datetime import datetime
from uuid import UUID
import asyncio

from mautrix.appservice import AppService
from mautrix.bridge import AutologinError, BaseUser, async_getter_lock
from mautrix.types import RoomID, UserID
from mautrix.util.logging import TraceLogger
from mautrix.util.bridge_state import BridgeState, BridgeStateEvent
from mautrix.util.opt_prometheus import Gauge

from mautrix_wechat import portal as po, puppet as pu
from mautrix_wechat.config import Config
from mautrix_wechat.db import User as DBUser
from wesdk.client import WechatClient
from wesdk.types import WechatID, WechatUser, TxtMessage, PicMessage, TxtCiteMessage

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class User(DBUser, BaseUser):
    by_mxid: dict[UserID, "User"] = {}
    by_wxid: dict[WechatID, "User"] = {}
    config: Config
    az: AppService
    loop: asyncio.AbstractEventLoop
    bridge: "WechatBridge"
    client: "WechatClient"

    relay_whitelisted: bool
    is_admin: bool
    permission_level: str

    def __init__(
        self,
        mxid: UserID,
        wxid: WechatID,
        wxname: str,
        wxcode: str,
        notice_room: Optional[WechatID] = None,
    ) -> None:
        super().__init__(mxid=mxid, wxid=wxid, wxname=wxname, wxcode=wxcode, notice_room=notice_room)
        BaseUser.__init__(self)
        self.client = None
        self.is_whitelisted, self.is_admin, self.level = self.config.get_permissions(mxid)
        self.groups = {}
        self.groups_lock = asyncio.Lock()
        self.users = {}
        self.users_lock = asyncio.Lock()
        self._intentional_disconnect = False
        self.periodic_sync_task = None

    @classmethod
    def init_cls(cls, bridge: "WechatBridge") -> None:
        cls.bridge = bridge
        cls.config = bridge.config
        cls.az = bridge.az
        cls.loop = bridge.loop

    def _postinit(self) -> None:
        self.by_mxid[self.mxid] = self
        if self.wxid:
            self.by_wxid[self.wxid] = self

    def login_complete(self, client: WechatClient) -> None:
        self.client = client

    @classmethod
    @async_getter_lock
    async def get_by_mxid(cls, mxid: UserID, create: bool = False) -> Optional["User"]:
        if pu.Puppet.get_id_from_mxid(mxid) or mxid == cls.az.bot_mxid:
            return None

        if mxid in cls.by_mxid:
            return cls.by_mxid[mxid]

        user = cast(cls, await super().get_by_mxid(mxid))
        if user:
            user._postinit()
        elif create:
            user = cls(mxid)
            await user.insert()
            user._postinit()
        return user

    @classmethod
    @async_getter_lock
    async def get_by_wxid(cls, wxid: WechatID) -> Optional["User"]:
        if wxid in cls.by_wxid:
            return cls.by_wxid

        user = cast(cls, await super().get_by_wxid(wxid))
        if user:
            user._postinit()
        return user

    async def is_logged_in(self) -> bool:
        return self.client.logged_in

    async def get_puppet(self) -> Optional[pu.Puppet]:
        if not self.wxid:
            return None
        return await pu.Puppet.get_by_wxid(self.wxid)

    async def get_portal_with(
        self, puppet: pu.Puppet, create: bool = True
    ) -> Optional["po.Portal"]:
        if not self.wxid:
            return None
        return await po.Portal.get_by_wxid(
            puppet.wxid, tg_receiver=self.wxid, create=create
        )