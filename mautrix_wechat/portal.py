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
    Deque
)
from uuid import UUID
from venv import create

from lxml import etree
from mautrix.appservice import AppService, IntentAPI

# from mausignald.types import Address, Contact, Profile
from mautrix.bridge import BasePortal, async_getter_lock, puppet
from mautrix.errors import MatrixError
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
from mautrix.util.message_send_checkpoint import MessageSendCheckpointStatus
from mautrix.util.simple_template import SimpleTemplate
from wesdk.types import Message as WechatMessage, PicMessage, TxtMessage, TxtCiteMessage
from wesdk.types import WechatID, WechatUser

import mautrix_wechat.user as u
from mautrix_wechat import formatter as fmt
from mautrix_wechat import matrix as m
from mautrix_wechat import puppet as p
from mautrix_wechat import wechat as w
from mautrix_wechat.config import Config
from mautrix_wechat.db import Message as DBMessage
from mautrix_wechat.db import Portal as DBPortal
from mautrix_wechat.util.locks import PortalSendLock
from mautrix_wechat.util.containers import SizedDict

if TYPE_CHECKING:
    from .__main__ import WechatBridge

StateBridge = EventType.find("m.bridge", EventType.Class.STATE)
StateHalfShotBridge = EventType.find("uk.half-shot.bridge", EventType.Class.STATE)


class BridgingError(Exception):
    pass


class IgnoredMessageError(Exception):
    pass


class Portal(DBPortal, BasePortal):
    by_mxid: Dict[RoomID, "Portal"] = {}
    by_wxid: Dict[Tuple[WechatID, WechatID], "Portal"] = {}
    config: Config
    matrix: "m.MatrixHandler"
    wechat: "w.WechatHandler"
    az: AppService
    private_chat_portal_meta: bool
    deleted: bool

    _main_intent: Optional[IntentAPI]
    _create_room_lock: asyncio.Lock
    _send_lock: PortalSendLock
    _msg_dedup: Deque[Tuple[str, WechatID, WechatID, datetime]]
    _msg_cache: Dict[Tuple[WechatID, WechatID, str], EventID]

    @classmethod
    def init_cls(cls, bridge: "WechatBridge") -> None:
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.az = bridge.az
        cls.loop = bridge.loop
        BasePortal.bridge = bridge

    def __init__(
        self,
        wxid: WechatID,
        receiver: WechatID,
        mxid: Optional[RoomID] = None,
        name: Optional[str] = None,
        avatar_url: Optional[ContentURI] = None,
        encrypted: bool = False,
    ) -> None:
        super().__init__(
            wxid=wxid,
            receiver=receiver,
            mxid=mxid,
            name=name,
            avatar_url=avatar_url,
            encrypted=encrypted,
        )
        BasePortal.__init__(self)
        self.deleted = False
        self.log = self.log.getChild(self.wxid)
        self._main_intent = None
        self.relay_user_id = None
        self._relay_user = None
        self._create_room_lock = asyncio.Lock()
        self._send_lock = PortalSendLock()
        self._msg_dedup = deque(maxlen=100)
        self._msg_cache = SizedDict(maxlen=100)

    async def _postinit(self) -> None:
        if self.wxid:
            self.by_wxid[(self.wxid, self.receiver)] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self

        if self.is_direct:
            puppet = await p.Puppet.get_by_wxid(self.wxid, create=True)
            puppet: p.Puppet
            self._main_intent = puppet.default_mxid_intent
        else:
            self._main_intent = self.az.intent

    @property
    def is_direct(self) -> bool:
        return not self.wxid.endswith("chatroom")

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
    def bridge_info(self) -> Dict[str, Any]:
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
    @async_getter_lock
    async def get_by_wxid(
        cls, wxid: WechatID, receiver: Optional[WechatID], create: bool = False
    ) -> Optional["Portal"]:
        if (wxid, receiver) in cls.by_wxid:
            return cls.by_wxid[(wxid, receiver)]

        portal = cast(cls, await super().get_by_wxid(wxid, receiver))
        if portal:
            await portal._postinit()
        elif create:
            portal = cls(wxid, receiver)
            await portal.insert()
            await portal._postinit()
        return portal

    @classmethod
    @async_getter_lock
    async def get_by_mxid(cls, mxid: RoomID) -> Optional["Portal"]:
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        portal = cast(cls, await super().get_by_mxid(mxid))
        if portal:
            await portal._postinit()
            return portal

        return None

    async def delete(self) -> None:
        try:
            del self.by_wxid[(self.wxid, self.receiver)]
        except KeyError:
            pass

        try:
            if self.mxid:
                del self.by_mxid[self.mxid]
        except KeyError:
            pass

        await super().delete()
        if self.mxid:
            await DBMessage.delete_all(self.mxid)
        self.deleted = True

    def _set_msg_cache(self, msg: WechatMessage, event_id: EventID) -> None:
        if isinstance(msg, TxtCiteMessage):
            msg: TxtCiteMessage
            title = etree.fromstring(msg.content).find("*//title")
            if title is not None:
                self._msg_cache[(msg.sender, msg.source, title.text.strip())] = event_id
        elif isinstance(msg, TxtMessage):
            msg: TxtMessage
            self._msg_cache[(msg.sender, msg.source, msg.content)] = event_id

    async def _send_delivery_receipt(self, event_id: EventID) -> None:
        if self.config["bridge.delivery_receipts"]:
            try:
                await self.az.intent.mark_read(self.mxid, event_id)
            except Exception:
                self.log.exception("Failed to send delivery receipt for %s", event_id)

    async def _send_message_status(
        self, event_id: EventID, err: Optional[Exception]
    ) -> None:
        if not self.config["bridge.message_status_events"]:
            return
        intent = self.az.intent if self.encrypted else self.main_intent
        status = BeeperMessageStatusEventContent(
            network=self.bridge_info_state_key,
            relates_to=RelatesTo(
                rel_type=RelationType.REFERENCE,
                event_id=event_id,
            ),
            success=err is None,
        )
        if err:
            status.reason = MessageStatusReason.GENERIC_ERROR
            status.error = str(err)
            status.is_certain = True
            status.can_retry = not isinstance(err, IgnoredMessageError)

        await intent.send_message_event(
            room_id=self.mxid,
            event_type=EventType.BEEPER_MESSAGE_STATUS,
            content=status,
        )

    async def _send_bridge_error(
        self,
        sender: u.User,
        err: Exception,
        event_id: EventID,
        event_type: EventType,
        message_type: Optional[MessageType] = None,
        msg: Optional[str] = None,
    ) -> None:
        sender.send_remote_checkpoint(
            MessageSendCheckpointStatus.PERM_FAILURE,
            event_id,
            self.mxid,
            event_type,
            message_type=message_type,
            error=err,
        )

        if self.config["bridge.delivery_error_reports"]:
            msg = TextMessageEventContent(
                msgtype=MessageType.NOTICE, body=msg or str(err)
            )
            msg.set_reply(event_id)
            await self._send_message(self.main_intent, msg)
        await self._send_message_status(event_id, err)

    async def handle_matrix_message(
        self, sender: u.User, content: MessageEventContent, event_id: EventID
    ) -> None:
        try:
            if not content.msgtype:
                raise IgnoredMessageError("Message doesn't have a msgtype")
            elif not content.body:
                raise IgnoredMessageError("Message doesn't have a body")

            if content.msgtype in (MessageType.TEXT,):
                async with self._send_lock(sender.wxid):
                    if self.receiver == sender.wxid:
                        msg, nick = await fmt.matrix_to_wechat(content, sender)
                        data = await sender.client.send_msg(msg, self.wxid, self.wxid, nickname=nick or "null")
                        self.log.debug(data)
                    # TODO: maybe user get_relay_sender
                    elif relay_user := await self.get_relay_user():
                        if relay_user.client.can_relay:
                            msg, nick = await fmt.matrix_to_wechat(content, sender, relay_user.client.show_sender)
                            data = await relay_user.client.send_msg(msg, self.wxid, self.wxid, nickname=nick or "null")
                            self.log.debug(data)
                    else:
                        raise IgnoredMessageError(f"Relaying message not supported!")
                # await self._handle_matrix_text(sender, content, event_id)
            else:
                raise IgnoredMessageError(
                    f"Message type {content.msgtype} not supported"
                )
        except Exception as e:
            self.log.exception(f"Failed to bridge {event_id}: {e}")
            await self._send_bridge_error(
                sender,
                e,
                event_id,
                EventType.ROOM_MESSAGE,
                message_type=content.msgtype,
            )

    async def handle_message(
        self,
        user: u.User,
        sender: p.Puppet,
        msg: WechatMessage,
        info: Optional[WechatUser] = None,
    ) -> None:
        if not self.mxid:
            await self.create_matrix_room(user, info)
            if not self.mxid:
                self.log.warning(
                    f"Failed to create room for incoming message ({msg.time}): {msg.content}"
                )
                return
        if (msg.id, msg.source, msg.sender, msg.time) in self._msg_dedup:
            self.log.debug(
                f"Ignoring message by {msg.sender} in {msg.source} at {msg.time} as it was already handled: {msg}"
            )
            return
        self._msg_dedup.appendleft((msg.id, msg.source, msg.sender, msg.time))

        if await DBMessage.get_by_wechat_id(
            msg.sender, msg.source, self.wxid, msg.time.timestamp()
        ):
            self.log.debug(
                f"Ignoring message by {msg.sender} in {msg.source} at {msg.time} as it was already handled: {msg}"
            )
            return
        self.log.debug(
            f"Start handling message {msg.id} by {msg.sender} in {msg.source} at {msg.time}"
        )
        self.log.trace(f"Message: {msg}")

        intent = sender.intent_for(self)
        content = await fmt.wechat_to_matrix(msg, self, self._msg_cache)
        event_id = await self._send_message(intent, content, timestamp=msg.time)
        if len(getattr(msg, 'content', '')):
            self._set_msg_cache(msg, event_id)
        await DBMessage(
            event_id,
            self.mxid,
            msg.id,
            msg.sender,
            msg.source,
            user.wxid,
            datetime.timestamp(msg.time),
        ).insert()

    def _get_invite_content(self, double_puppet: Optional[p.Puppet]) -> Dict[str, Any]:
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

    def _get_name(
        self, info: Optional[WechatID] = None, is_self: bool = False
    ) -> Optional[str]:
        name = None
        if self.is_direct:
            if is_self:
                name = "FileHelper"
            elif info and info.name:
                name = info.name + " (Wechat)"
            else:
                name = "未知私聊"
        elif info and info.name:
            name = info.name
        elif info and info.chat_room_members:
            name = f"群聊 ({len(info.chat_room_members)})"
        else:
            name = "未命名群聊"
        return name

    async def _update_name(self, name: str, save: bool = False) -> bool:
        if self.name == name:
            return False
        self.name = name or None
        if self.name:
            await self.main_intent.set_room_name(self.mxid, self.name)
        if save:
            await self.save()
        return True

    async def _update_avatar(self, avatar_url: ContentURI, save: bool = False) -> bool:
        if self.avatar_url == avatar_url:
            return False
        self.avatar_url = avatar_url or None
        if self.avatar_url:
            await self.main_intent.set_room_avatar(self.mxid, self.avatar_url)
        if save:
            await self.save()
        return True

    async def update_info(
        self, user: u.User, info: Optional[WechatUser] = None
    ) -> None:
        changed = False
        self.log.debug(f"Updating portal info for {self.mxid} {self.name}")
        try:
            if info:
                # TODO: not sure if name and avatar need to be updated in this case
                # becasue we're calling update_bridge_info anyway
                changed = await self._update_name(
                    self._get_name(info, user.wxid == self.wxid)
                )
                changed = await self._update_avatar(info.headimg) or changed
        except Exception:
            self.log.exception(f"Failed to update info for {self.mxid}")
        if changed:
            await self.save()
            await self.update_bridge_info()

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
        self, user: u.User, info: Optional[WechatUser] = None
    ) -> Optional[RoomID]:
        if self.mxid:
            await self.update_matrix_room(user, info)

        async with self._create_room_lock:
            try:
                return await self._create_matrix_room(user, info)
            except Exception as e:
                self.log.exception("Failed to create portal room")

    async def _update_participants(self, source: u.User) -> None:
        pass

    async def _create_matrix_room(
        self, user: u.User, info: Optional[WechatUser] = None
    ) -> Optional[RoomID]:
        if self.mxid:
            return self.mxid

        self.log.debug(f"Creating matrix room for {self.wxid}")

        puppet = await self.get_dm_puppet()
        if puppet and info:
            # TODO: not sure if this is needed
            await puppet.update_info(info)

        name = self.name = self._get_name(info, user.wxid == self.wxid)

        if info and info.headimg:
            self.avatar_url = info.headimg

        power_levels = PowerLevelStateEventContent()
        # TODO: maybe we want more fine-grained power level here
        power_levels.users[user.mxid] = 100
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
                # TODO: remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
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

        creation_content = {}
        if not self.config["bridge.federate_rooms"]:
            creation_content["m.federate"] = False
        self.mxid = await self.main_intent.create_room(
            name=name,
            is_direct=self.is_direct,
            invitees=invites,
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
        await self.save()
        self.log.debug(f"Matrix room created: {self.mxid}")
        self.by_mxid[self.mxid] = self
        # await self._update_participants(source)

        puppet = await p.Puppet.get_by_custom_mxid(user.mxid)
        await self.main_intent.invite_user(
            self.mxid, user.mxid, extra_content=self._get_invite_content(puppet)
        )
        if puppet:
            try:
                puppet: p.Puppet
                if self.is_direct:
                    await user.update_direct_chats({self.main_intent.mxid: [self.mxid]})

                await puppet.intent.join_room_by_id(self.mxid)
            except MatrixError:
                self.log.debug(
                    "Failed to join custom puppet into newly created portal",
                    exc_info=True,
                )
        # if not self.is_direct:
        #     await self._update_participants(source, info)
        return self.mxid

    async def update_matrix_room(
        self, user: u.User, info: Optional[WechatUser] = None
    ) -> None:
        try:
            self.log.debug(f"Updating matrix room for {self.wxid}")
            puppet = await p.Puppet.get_by_custom_mxid(user.mxid)
            # TODO: this is invite user no matter user has left or not
            await self.main_intent.invite_user(
                self.mxid, user.mxid, extra_content=self._get_invite_content(puppet)
            )

            if puppet:
                puppet: p.Puppet
                did_join = await puppet.intent.ensure_joined(self.mxid)
                if did_join and self.is_direct:
                    await user.update_direct_chats({self.main_intent.mxid: [self.mxid]})
            await self.update_info(user, info)

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
