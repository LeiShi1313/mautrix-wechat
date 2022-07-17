from uuid import UUID
from typing import Optional, ClassVar, List, TYPE_CHECKING

from attr import dataclass
from yarl import URL

from mautrix.types import UserID, SyncToken, ContentURI
from mautrix.util.async_db import Database
from wesdk.types import WechatID

fake_db = Database("") if TYPE_CHECKING else None


@dataclass
class Puppet:
    db: ClassVar[Database] = fake_db

    wxid: WechatID
    headimg: str
    name: str
    remarks: str
    wxcode: str
    is_registered: bool

    custom_mxid: Optional[UserID]
    access_token: Optional[str]
    next_batch: Optional[SyncToken]
    base_url: Optional[URL]
    avatar_url: Optional[ContentURI]

    async def insert(self) -> None:
        q = (
            "INSERT INTO puppet (wxid, headimg, name, remarks, wxcode, is_registered, "
            "                    custom_mxid, access_token, next_batch, base_url, avatar_url) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
        )
        await self.db.execute(
            q,
            self.wxid,
            self.headimg,
            self.name,
            self.remarks,
            self.wxcode,
            self.is_registered,
            self.custom_mxid,
            self.access_token,
            self.next_batch,
            self.base_url,
            self.avatar_url
        )

    async def save(self) -> None:
        q = (
            "UPDATE puppet SET headimg=$2, name=$3, remarks=$4, wxcode=$5, is_registered=$6, "
            "                  custom_mxid=$7, access_token=$8, next_batch=$9, base_url=$10, avatar_url=$11 "
            "WHERE wxid=$1"
        )
        await self.db.execute(
            q,
            self.wxid,
            self.headimg,
            self.name,
            self.remarks,
            self.wxcode,
            self.is_registered,
            self.custom_mxid,
            self.access_token,
            self.next_batch,
            self.base_url,
            self.avatar_url
        )

    @classmethod
    async def get_by_wxid(cls, wxid: WechatID) -> Optional["Puppet"]:
        q = (
            "SELECT wxid, headimg, name, remarks, wxcode, is_registered, "
            "       custom_mxid, access_token, next_batch, base_url, avatar_url "
            "FROM puppet WHERE wxid=$1"
        )
        row = await cls.db.fetchrow(q, wxid)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_custom_mxid(cls, mxid: UserID) -> Optional["Puppet"]:
        q = (
            "SELECT wxid, headimg, name, remarks, wxcode, is_registered, "
            "       custom_mxid, access_token, next_batch, base_url, avatar_url "
            "FROM puppet WHERE custom_mxid=$1"
        )
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def all_with_custom_mxid(cls) -> List["Puppet"]:
        q = (
            "SELECT wxid, headimg, name, remarks, wxcode, is_registered, "
            "       custom_mxid, access_token, next_batch, base_url, avatar_url "
            "FROM puppet WHERE custom_mxid IS NOT NULL"
        )
        rows = await cls.db.fetch(q)
        return [cls(**row) for row in rows]
