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
from dataclasses import fields

from yarl import URL
from mautrix.bridge import BasePuppet, async_getter_lock
from mautrix.appservice import IntentAPI
from mautrix.types import UserID, SyncToken
from mautrix.types import UserID, SyncToken, RoomID, ContentURI
from mautrix.util.simple_template import SimpleTemplate

from mautrix_wechat.db import Puppet as DBPuppet, puppet
from mautrix_wechat.config import Config
from mautrix_wechat.util.file import download_and_upload_file

from mautrix_wechat import portal as p
from wesdk.types import ChatRoomNick, WechatID, WechatUserDetail, WechatUser

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class Puppet(DBPuppet, BasePuppet):
    config: Config

    by_wxid: Dict[WechatID, "Puppet"] = {}
    by_custom_mxid: Dict[UserID, "Puppet"] = {}
    hs_domain: str
    mxid_template: SimpleTemplate[str]
    displayname_template: str
    default_mxid_intent: IntentAPI

    def __init__(
        self,
        wxid: WechatID,
        headimg: Optional[str] = None,
        name: Optional[str] = None,
        remarks: Optional[str] = None,
        wxcode: Optional[str] = None,
        is_registered: bool = False,
        custom_mxid: Optional[UserID] = None,
        access_token: Optional[str] = None,
        next_batch: Optional[SyncToken] = None,
        base_url: Optional[URL] = None,
        avatar_url: Optional[ContentURI] = None,
    ) -> None:
        super().__init__(
            wxid=wxid,
            headimg=headimg,
            name=name,
            remarks=remarks,
            wxcode=wxcode,
            is_registered=is_registered,
            custom_mxid=custom_mxid,
            access_token=access_token,
            next_batch=next_batch,
            base_url=base_url,
            avatar_url=avatar_url,
        )
        self.default_mxid = self.get_mxid_from_wxid(wxid, wxcode)
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
        cls.displayname_template = cls.config["bridge.displayname_template"]

    def _postinit(self) -> None:
        self.by_wxid[self.wxid] = self
        if self.custom_mxid:
            self.by_custom_mxid[self.custom_mxid] = self

    async def _update_avatar(self, headimg: str) -> bool:
        if headimg and headimg != self.headimg:
            self.log.debug(f"prev: {self.headimg} now: {headimg}")
            if headimg:
                photo_mxc = await download_and_upload_file(
                    headimg, self.default_mxid_intent, self.config
                )
                self.avatar_url = photo_mxc
            else:
                self.avatar_url = ContentURI("")
            try:
                await self.default_mxid_intent.set_avatar_url(self.avatar_url)
            except Exception:
                # TODO: may want to clear avatar_url when api fails
                self.log.exception("Failed to set avatar")
                return False
            self.headimg = headimg
            return True
        return False

    async def _update_name(self, name: str) -> bool:
        if name != self.name:
            if name:
                try:
                    await self.default_mxid_intent.set_displayname(
                        self.get_displayname(name, self.wxid)
                    )
                except Exception:
                    self.log.exception("Failed to set displayname")
                    return False
                self.name = name
                return True
        return False

    async def update_info(
        self,
        wechat_user: WechatUser = None,
        wechat_user_detail: WechatUserDetail = None,
        chat_room_nick: ChatRoomNick = None,
    ) -> None:
        self.log.debug(
            f"Updating info, WechatUser: {wechat_user}, WechatUserDetail: {wechat_user_detail}, ChatRoomNick: {chat_room_nick}"
        )
        changed: bool = False
        name = None
        if chat_room_nick and chat_room_nick.nick:
            name = chat_room_nick.nick
        if wechat_user:
            for field in fields(WechatUser):
                if val := getattr(wechat_user, field.name):
                    if field.name == "name":
                        name = val
                    elif val != getattr(self, field.name):
                        setattr(self, field.name, val)
        changed = await self._update_name(name)

        headimg = None
        if wechat_user and wechat_user.headimg:
            headimg = wechat_user.headimg
        if wechat_user_detail:
            detail_headimg = next(
                (
                    img
                    for img in [
                        wechat_user_detail.big_headimg,
                        wechat_user_detail.little_headimg,
                    ]
                    if img
                ),
                None,
            )
            if detail_headimg and detail_headimg != self.headimg:
                headimg = wechat_user_detail.little_headimg
        changed = await self._update_avatar(headimg) or changed
        if changed:
            await self.save()

    def intent_for(self, portal: "p.Portal") -> IntentAPI:
        if portal.wxid == self.wxid:
            return self.default_mxid_intent
        return self.intent

    @classmethod
    @async_getter_lock
    async def get_by_wxid(
        cls, wxid: WechatID, create: bool = False
    ) -> Optional["Puppet"]:
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
    async def get_by_mxid(
        cls, mxid: UserID, create: bool = False
    ) -> Optional["Puppet"]:
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
    def get_mxid_from_wxid(cls, wxid: WechatID, wxcode: Optional[WechatID]) -> UserID:
        return UserID(cls.mxid_template.format_full(wxcode if wxcode else wxid))

    @classmethod
    def get_displayname(cls, full_name: str, wxid: str) -> str:
        return cls.displayname_template.format(full_name=full_name, wxid=wxid)
