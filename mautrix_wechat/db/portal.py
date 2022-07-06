from uuid import UUID
from typing import Optional, ClassVar, List, Union, TYPE_CHECKING

import asyncpg
from attr import dataclass

from mautrix.types import RoomID
from mautrix.util.async_db import Database
from wesdk.types import WechatID

fake_db = Database("") if TYPE_CHECKING else None


@dataclass
class Portal:
    db: ClassVar[Database] = fake_db

    wxid: WechatID
    receiver: WechatID
    mxid: Optional[RoomID]
    name: Optional[str]
    encrypted: bool

    async def insert(self) -> None:
        q = ("INSERT INTO portal (wxid, receiver, mxid, name, encrypted) "
             "VALUES ($1, $2, $3, $4, $5)")
        await self.db.execute(q, self.wxid, self.receiver, self.mxid, self.name, self.encrypted)

    async def update(self) -> None:
        q = ("UPDATE portal SET mxid=$3, name=$4, encrypted=$5 "
             "WHERE wxid=$1::text and receiver=$2::text")
        await self.db.execute(q, self.wxid, self.receiver, self.mxid, self.name, self.encrypted)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> 'Portal':
        data = {**row}
        wxid = data.pop("wxid")
        return cls(wxid=wxid, **data)

    @classmethod
    async def get_by_mxid(cls, mxid: RoomID) -> Optional['Portal']:
        q = ("SELECT wxid, receiver, mxid, name, encrypted "
             "FROM portal WHERE mxid=$1")
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_wxid(cls, wxid: WechatID, receiver: WechatID) -> Optional['Portal']:
        q = ("SELECT wxid, receiver, mxid, name, encrypted "
             "FROM portal WHERE wxid=$1::text AND receiver=$2::text")
        row = await cls.db.fetchrow(q, wxid, receiver)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def all_with_room(cls) -> List['Portal']:
        q = "SELECT wxid, receiver, mxid, name, encrypted FROM portal WHERE mxid IS NOT NULL"
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]

    @classmethod
    async def all(cls) -> List['Portal']:
        q = f"SELECT wxid, receiver, mxid, name, encrypted FROM portal"
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
    