from uuid import UUID
from typing import Optional, ClassVar, List, TYPE_CHECKING

from attr import dataclass

from mautrix.types import UserID, RoomID
from mautrix.util.async_db import Database
from wesdk.types import WechatID

fake_db = Database("") if TYPE_CHECKING else None


@dataclass
class User:
    db: ClassVar[Database] = fake_db

    mxid: UserID
    wxid: WechatID
    wxname: Optional[str]
    wxcode: Optional[str]
    notice_room: Optional[RoomID]

    async def insert(self) -> None:
        q = ('INSERT INTO "user" (mxid, wxid, wxname, wxcode, notice_room) '
             'VALUES ($1, $2, $3, $4, $5)')
        await self.db.execute(q, self.mxid, self.wxid, self.wxname, self.wxcode, self.notice_room)

    async def save(self) -> None:
        q = ('UPDATE "user" SET mxid=$2, wxname=$3, wxcode=$4, notice_room=$5 '
             'WHERE wxid=$1')
        await self.db.execute(q, self.wxid, self.mxid, self.wxname, self.wxcode, self.notice_room)

    @classmethod
    async def get_by_mxid(cls, mxid: UserID) -> Optional['User']:
        q = 'SELECT mxid, wxid, wxname, wxcode, notice_room FROM "user" WHERE mxid=$1'
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_wxid(cls, wxid: WechatID) -> Optional['User']:
        q = 'SELECT mxid, wxid, wxname, wxcode, notice_room FROM "user" WHERE wxid=$1'
        row = await cls.db.fetchrow(q, wxid)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def all_logged_in(cls) -> List['User']:
        q = 'SELECT mxid, wxid, wxname, wxcode, notice_room FROM "user" WHERE wxid IS NOT NULL'
        rows = await cls.db.fetch(q)
        return [cls(**row) for row in rows]