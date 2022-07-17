from asyncpg import Connection

from mautrix.util.async_db import UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute("""CREATE TABLE portal (
        wxid        TEXT,
        receiver    TEXT,
        mxid        TEXT,
        name        TEXT,
        avatar_url  TEXT,
        encrypted   BOOLEAN NOT NULL DEFAULT false,
        PRIMARY KEY (wxid, receiver)
    )""")
    await conn.execute("""CREATE TABLE "user" (
        mxid        TEXT PRIMARY KEY,
        wxid        TEXT UNIQUE,
        wxname      TEXT,
        wxcode      TEXT,
        notice_room TEXT
    )""")
    await conn.execute("""CREATE TABLE puppet (
        wxid          TEXT PRIMARY KEY,
        headimg       TEXT,
        name          TEXT,
        remarks       TEXT,
        wxcode        TEXT,
        is_registered BOOLEAN NOT NULL DEFAULT false,
        custom_mxid   TEXT,
        access_token  TEXT,
        next_batch    TEXT,
        base_url      TEXT,
        avatar_url    TEXT
    )""")
    await conn.execute("""CREATE TABLE message (
        mxid    TEXT NOT NULL,
        mx_room TEXT NOT NULL,
        id              TEXT,
        sender          TEXT,
        source          TEXT,
        receiver        TEXT,
        timestamp       BIGINT,
        PRIMARY KEY (sender, source, receiver, timestamp),
        FOREIGN KEY (source, receiver) REFERENCES portal(wxid, receiver)
            ON UPDATE CASCADE ON DELETE CASCADE,
        UNIQUE (mxid, mx_room)
    )""")