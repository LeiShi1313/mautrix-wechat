from uuid import UUID
from typing import Optional, ClassVar, Union, List, TYPE_CHECKING

import asyncpg
from attr import dataclass

from mautrix.types import RoomID, EventID
from mautrix.util.async_db import Database
from wesdk.types import WechatID

fake_db = Database("") if TYPE_CHECKING else None


@dataclass
class Message:
    db: ClassVar[Database] = fake_db

    mxid: EventID
    mx_room: RoomID
    id: str
    sender: WechatID
    source: WechatID
    receiver: WechatID
    timestamp: int

    async def insert(self) -> None:
        q = (
            "INSERT INTO message (mxid, mx_room, id, sender, source, receiver, timestamp)"
            "                         VALUES ($1, $2, $3, $4, $5, $6, $7)"
        )
        await self.db.execute(
            q,
            self.mxid,
            self.mx_room,
            self.id,
            self.sender,
            self.source,
            self.receiver,
            self.timestamp,
        )

    async def delete(self) -> None:
        q = (
            "DELETE FROM message WHERE sender=$1 AND source=$2"
            "                          AND receiver=$3 AND timestamp=$4"
        )
        await self.db.execute(
            q, self.sender, self.source, self.receiver, self.timestamp
        )

    @classmethod
    async def delete_all(cls, room_id: RoomID) -> None:
        await cls.db.execute("DELETE FROM message WHERE mx_room=$1", room_id)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> "Message":
        data = {**row}
        source = data.pop("source")
        return cls(source=source, **data)

    @classmethod
    async def get_by_mxid(cls, mxid: EventID) -> Optional["Message"]:
        q = (
            "SELECT mxid, mx_room, id, sender, source, receiver, timestamp "
            "FROM message WHERE mxid=$1"
        )
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_wechat_id(
        cls, sender: WechatID, source: WechatID, receiver: WechatID, timestamp: int
    ) -> Optional["Message"]:
        q = (
            "SELECT mxid, mx_room, id, sender, source, receiver, timestamp "
            "FROM message WHERE sender=$1 AND source=$2 AND receiver=$3 AND timestamp=$4"
        )
        row = await cls.db.fetchrow(q, sender, source, receiver, timestamp)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def find_by_timestamps(cls, timestamps: List[int]) -> List["Message"]:
        q = (
            "SELECT mxid, mx_room, id, sender, source, receiver, timestamp "
            "FROM message WHERE timestamp=ANY($1)"
        )
        rows = await cls.db.fetch(q, timestamps)
        return [cls(**row) for row in rows]

    @classmethod
    async def find_by_sender_content(
        cls, sender: WechatID, timestamp: int
    ) -> Optional["Message"]:
        q = (
            "SELECT mxid, mx_room, id, sender, source, receiver, timestamp "
            "FROM message WHERE sender=$1 AND timestamp=$2"
        )
        row = await cls.db.fetchrow(q, sender, timestamp)
        if not row:
            return None
        return cls(**row)
