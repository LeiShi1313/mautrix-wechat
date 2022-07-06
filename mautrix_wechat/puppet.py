from optparse import Option
from typing import (
    Optional,
    Dict,
    AsyncIterable,
    Awaitable,
    AsyncGenerator,
    Union,
    TYPE_CHECKING,
    cast,
)
from uuid import UUID
import asyncio

from yarl import URL
from mautrix.bridge import BasePuppet, async_getter_lock
from mautrix.appservice import IntentAPI
from mautrix.types import UserID, SyncToken
from mautrix.types import UserID, SyncToken, RoomID
from mautrix.util.simple_template import SimpleTemplate

from mautrix_wechat.db import Puppet as DBPuppet, puppet
from mautrix_wechat.config import Config
# from mautrix_wechat import portal as p
from wesdk.types import WechatID

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class Puppet(DBPuppet, BasePuppet):
    config: Config

    by_wxid: dict[WechatID, "Puppet"] = {}
    by_custom_mxid: dict[UserID, "Puppet"] = {}
    hs_domain: str
    mxid_template: SimpleTemplate[str]
    default_mxid_intent: IntentAPI

    def __init__(
        self,
        wxid: WechatID,
        headimg: str,
        name: str,
        remarks: str,
        wxcode: str,
        custom_mxid: Optional[UserID],
        access_token: Optional[str],
        next_batch: Optional[SyncToken],
        base_url: Optional[URL],
    ) -> None:
        super().__init__(
            wxid=wxid,
            headimg=headimg,
            name=name,
            remarks=remarks,
            wxcode=wxcode,
            custom_mxid=custom_mxid,
            access_token=access_token,
            next_batch=next_batch,
            base_url=base_url,
        )
        self.default_mxid = self.get_mxid_from_wxid(wxid)
        self.default_mxid_intent = self.az.intent.user(self.default_mxid)
        self.intent = self._fresh_intent()

        self.log = self.log.getChild(self.wxid)

    @classmethod
    def init_cls(cls, bridge: "WechatBridge") -> None:
        cls.config = bridge.config
        cls.loop = bridge.loop
        cls.mx = bridge.matrix
        cls.az = bridge.az
        cls.hs_domain = cls.config["homeserver"]["domain"]
        cls.mxid_template = SimpleTemplate(
            cls.config["bridge.username_template"],
            "userid",
            prefix="@",
            suffix=f":{cls.hs_domain}",
            type=str,
        )

    def _postinit(self) -> None:
        self.by_wxid[self.wxid] = self
        if self.custom_mxid:
            self.by_custom_mxid[self.custom_mxid] = self

    @classmethod
    @async_getter_lock
    async def get_by_wxid(cls, wxid: WechatID, create: bool = False) -> Optional["Puppet"]:
        if wxid in cls.by_wxid:
            return cls.by_wxid[wxid]
        
        puppet = cast(Puppet, await super().get_by_wxid(wxid))
        if puppet:
            puppet._postinit()
        elif create:
            puppet = cls(wxid)
            await puppet.insert()
            puppet._postinit()
        return puppet

    @classmethod
    @async_getter_lock
    async def get_by_mxid(cls, mxid: UserID, create: bool = False) -> Optional["Puppet"]:
        wxid = cls.get_id_from_mxid(mxid)
        if wxid:
            return await cls.get_by_wxid(wxid, create)
        return None

    @classmethod
    @async_getter_lock
    async def get_by_custom_mxid(cls, mxid: UserID) -> Optional["Puppet"]:
        if mxid in cls.by_custom_mxid:
            return cls.by_custom_mxid[mxid]
        puppet = cast(Puppet, await super().get_by_custom_mxid(mxid))
        if puppet:
            puppet._postinit()
        return puppet

    @classmethod
    def get_id_from_mxid(cls, mxid: UserID) -> Optional[str]:
        return cls.mxid_template.parse(mxid)

    @classmethod
    def get_mxid_from_wxid(cls, wxid: WechatID) -> UserID:
        return UserID(cls.mxid_template.format_full(wxid))
