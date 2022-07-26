from typing import TYPE_CHECKING, List, Union

from mautrix.bridge import BaseMatrixHandler
from mautrix.types import (EncryptedEvent, Event, EventID, EventType,
                           MessageEvent, PresenceEvent, PresenceEventContent,
                           ReactionEvent, ReactionEventContent, ReceiptEvent,
                           RedactionEvent, RelationType, RoomID, StateEvent,
                           TypingEvent, UserID)

from mautrix_wechat import commands as com
from mautrix_wechat import portal as po
from mautrix_wechat import puppet as pu
from mautrix_wechat import user as u
from mautrix_wechat.db import Message as DBMessage

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class MatrixHandler(BaseMatrixHandler):
    def __init__(self, bridge: "WechatBridge") -> None:
        prefix, suffix = bridge.config["bridge.username_template"].format(userid=":").split(":")
        homeserver = bridge.config['homeserver.domain']
        self.user_id_prefix = f"@{prefix}"
        self.user_id_suffix = f"{suffix}:{homeserver}"

        super().__init__(bridge=bridge)

    
    async def send_welcome_message(self, room_id: RoomID, inviter: "u.User") -> None:
        await super().send_welcome_message(room_id, inviter)
        if not inviter.notice_room:
            inviter.notice_room = room_id
            await inviter.update()
            await self.az.intent.send_notice(room_id, "This room has been marked as your Wechat bridge notice room.")

    async def handle_leave(self, room_id: RoomID, user_id: UserID, event_id: EventID) -> None:
        pass

    async def handle_kick(
        self, room_id: RoomID, user_id: UserID, kicked_by: UserID, reason: str, event_id: EventID
    ) -> None:
        pass

    async def handle_ban(
        self, room_id: RoomID, user_id: UserID, banned_by: UserID, reason: str, event_id: EventID
    ) -> None:
        pass

    async def handle_unban(
        self, room_id: RoomID, user_id: UserID, unbanned_by: UserID, reason: str, event_id: EventID
    ) -> None:
        pass

    async def handle_join(self, room_id: RoomID, user_id: UserID, event_id: EventID) -> None:
        pass
