import asyncio
from collections import deque
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Dict,
    Optional,
    Tuple,
    Union,
    cast,
)
from uuid import UUID
from venv import create

from mautrix.appservice import AppService, IntentAPI
from mautrix.errors import MatrixError

# from mausignald.types import Address, Contact, Profile
from mautrix.bridge import BasePortal
from mautrix.types import (
    BeeperMessageStatusEventContent,
    ContentURI,
    EncryptionAlgorithm,
    EventID,
    EventType,
    ImageInfo,
    MediaMessageEventContent,
    Membership,
    MessageEventContent,
    MessageStatusReason,
    MessageType,
    PowerLevelStateEventContent,
    RelatesTo,
    RelationType,
    RoomID,
    TextMessageEventContent,
    UserID,
)
from mautrix.util.simple_template import SimpleTemplate
from wesdk.types import TxtMessage, WechatID, WechatUser

from mautrix_wechat import matrix as m
from mautrix_wechat import puppet as p
from mautrix_wechat import user as u
from mautrix_wechat import wechat as w
from mautrix_wechat.config import Config
from mautrix_wechat.db import Message as DBMessage
from mautrix_wechat.db import Portal as DBPortal

if TYPE_CHECKING:
    from .__main__ import WechatBridge

StateBridge = EventType.find("m.bridge", EventType.Class.STATE)
StateHalfShotBridge = EventType.find("uk.half-shot.bridge", EventType.Class.STATE)


class Portal(DBPortal, BasePortal):
    by_mxid: Dict[RoomID, "Portal"] = {}
    by_wxid: Dict[Tuple[WechatID, WechatID], "Portal"] = {}
    config: Config
    matrix: "m.MatrixHandler"
    signal: "w.WechatHandler"
    az: AppService
    private_chat_portal_meta: bool

    _main_intent: Optional[IntentAPI]
    _create_room_lock: asyncio.Lock
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
        self._create_room_lock = asyncio.Lock()
        self._msg_dedup = deque(maxlen=100)

    async def _postinit(self) -> None:
        if self.wxid:
            self.by_wxid[(self.wxid, self.receiver)] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self

        # self._main_intent = puppet.intent_for(self) if self.is_direct else self.az.intent
        if self.is_direct:
            puppet = await p.Puppet.get_by_wxid(self.wxid, create=True)
            self._main_intent = puppet.default_mxid_intent
        else:
            self._main_intent = self.az.intent

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError(
                "Portal must be _postinit()ed before main_intent can be used"
            )
        return self._main_intent

    @property
    def bridge_info_state_key(self) -> str:
        return f"net.maunium.wechat://wechat/{self.wxid}"

    @property
    def bridge_info(self) -> dict[str, Any]:
        info = {
            "bridgebot": self.az.bot_mxid,
            "creator": self.main_intent.mxid,
            "protocol": {
                "id": "wechat",
                "displayname": "Wechat",
                "avatar_url": self.config["appservice.bot_avatar"],
            },
            "channel": {
                "id": self.mxid,
                "displayname": self.name,
                "avatar_url": self.avatar_url,
            },
        }
        return info

    @classmethod
    async def get_by_wxid(
        cls, wxid: WechatID, receiver: Optional[WechatID], create: bool = False
    ) -> Optional["Portal"]:
        if (wxid, receiver) in cls.by_wxid:
            return cls.by_wxid[(wxid, receiver)]

        portal = cast(cls, await super().get_by_wxid(wxid, receiver))
        if portal:
            await portal._postinit()
        elif create:
            portal = cls(wxid)
            await portal.insert()
            await portal._postinit()
        return portal

    async def handle_txt_message(
        self, source: u.User, sender: p.Puppet, msg: TxtMessage
    ) -> None:
        if not self.mxid:
            await self.create_matrix_room()
            if not self.mxid:
                self.log.warning(
                    f"Failed to create room for incoming message ({msg.timestamp}): {msg.content}"
                )
                return
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
        self.log.debug(
            f"Start handling message by {msg.user} in {msg.source} at {msg.time}"
        )
        self.log.trace(f"Message content: {msg.content}")

    def _get_invite_content(self, double_puppet: Optional[p.Puppet]) -> dict[str, Any]:
        invite_content = {}
        if double_puppet:
            invite_content["fi.mau.will_auto_accept"] = True
        if self.is_direct:
            invite_content["is_direct"] = True
        return invite_content

    async def get_dm_puppet(self) -> Optional[p.Puppet]:
        if not self.is_direct:
            return None
        return await p.Puppet.get_by_wxid(self.wxid, create=True)

    async def update_info(self, source: u.User, info: WechatUser) -> None:
        changed = False
        self.log.debug("Updating info for {self.mxid}")
        try:
            changed = await self._update_name(info.name)
        except Exception:
            self.log.exception(f"Failed to update info for {self.mxid}")
        if changed:
            await self.update()
            await self.update_bridge_info()

    async def _update_name(self, name: str, save: bool = False) -> bool:
        if self.name == name:
            return False
        self.name = name or None
        # if self.name:
        # await self.main_intent.add_room_alias(self.mxid, self.alias_localpart, override=True)
        if save:
            await self.update()
        return True

    async def update_bridge_info(self) -> None:
        if not self.mxid:
            self.log.debug("Not updating bridge info: no Matrix room created")
            return

        try:
            self.log.debug(f"Updating bridge info for {self.mxid}")
            await self.main_intent.send_state_event(
                self.mxid, StateBridge, self.bridge_info, self.bridge_info_state_key
            )
            # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
            await self.main_intent.send_state_event(
                self.mxid,
                StateHalfShotBridge,
                self.bridge_info,
                self.bridge_info_state_key,
            )
        except Exception:
            self.log.warning("Failed to update bridge info", exc_info=True)

    async def create_matrix_room(
        self, source: u.User, info: WechatUser
    ) -> Optional[RoomID]:
        if self.mxid:
            await self.update_matrix_room(source, info)

        async with self._create_room_lock:
            try:
                return await self._create_matrix_room(source)
            except Exception as e:
                self.log.exception("Failed to create portal room")

    async def _create_matrix_room(
        self, source: u.User, info: WechatUser
    ) -> Optional[RoomID]:
        if self.mxid:
            return self.mxid

        self.log.debug(f"Creating matrix room for {self.wxid}")

        self.receiver = source
        self.name = info.name

        puppet = await self.get_dm_puppet()
        if puppet:
            await puppet.update_info(source, info)

        power_levels = PowerLevelStateEventContent()
        if self.is_direct:
            power_levels.users[source.mxid] = 50
        power_levels.users[self.main_intent.mxid] = 100
        initial_state = [
            {
                "type": EventType.ROOM_POWER_LEVELS.serialize(),
                "content": power_levels.serialize(),
            },
            {
                "type": str(StateBridge),
                "state_key": self.bridge_info_state_key,
                "content": self.bridge_info,
            },
            {
                # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
                "type": str(StateHalfShotBridge),
                "state_key": self.bridge_info_state_key,
                "content": self.bridge_info,
            },
        ]
        invites = []
        if self.config["bridge.encryption.default"] and self.matrix.e2ee:
            self.encrypted = True
            initial_state.append(
                {
                    "type": str(EventType.ROOM_ENCRYPTION),
                    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                }
            )
            if self.is_direct:
                invites.append(self.az.bot_mxid)
        if self.is_direct and source.wxid == self.wxid:
            name = self.name = "FileHelper"
        elif self.encrypted or self.private_chat_portal_meta or not self.is_direct:
            name = self.name

        creation_content = {}
        if not self.config["bridge.federate_rooms"]:
            creation_content["m.federate"] = False
        self.mxid = await self.main_intent.create_room(
            name=name,
            # topic=self.topic,
            is_direct=self.is_direct,
            invite=invites,
            initial_state=initial_state,
            creation_content=creation_content,
            power_level_override={"users": {self.main_intent.mxid: 9001}},
        )
        if not self.mxid:
            raise Exception("Failed to create room: no mxid returned")

        if self.encrypted and self.matrix.e2ee and self.is_direct:
            try:
                await self.az.intent.ensure_joined(self.mxid)
            except Exception:
                self.log.warning(
                    f"Failed to add bridge bot to new private chat {self.mxid}"
                )
        await self.update()
        self.log.debug(f"Matrix room created: {self.mxid}")
        self.by_mxid[self.mxid] = self

        puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
        await self.main_intent.invite_user(
            self.mxid, source.mxid, extra_content=self._get_invite_content(puppet)
        )
        if puppet:
            try:
                await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})
                await puppet.intent.join_room_by_id(self.mxid)
            except MatrixError:
                self.log.debug(
                    "Failed to join custom puppet into newly created portal",
                    exc_info=True,
                )
        # if not self.is_direct:
        #     await self._update_participants(source, info)
        return self.mxid

    async def update_matrix_room(self, source: u.User, info: WechatUser) -> None:
        try:
            self.log.debug(f"Updating matrix room for {self.wxid}")
            puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
            await self.main_intent.invite_user(
                self.mxid, source.mxid, extra_content=self._get_invite_content(puppet)
            )

            if puppet:
                did_join = await puppet.intent.ensure_joined(self.mxid)
                if did_join and self.is_direct:
                    await source.update_direct_chats(
                        {self.main_intent.mxid: [self.mxid]}
                    )
            # if self.is_direct:
            # await self.main_intent.update_room(self.mxid, name=info.name)
            await self.update_info(source, info)

            self.log.debug(f"Matrix room updated: {self.mxid}")
        except Exception:
            self.log.exception("Failed to update matrix room")

    @classmethod
    async def all(cls) -> AsyncIterable["Portal"]:
        portal: "Portal"
        for portal in await super().all():
            try:
                yield cls.by_wxid[(portal.wxid, portal.receiver)]
            except KeyError:
                await portal._postinit()
                yield portal
