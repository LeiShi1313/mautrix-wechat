from mautrix.util.async_db import Database

from mautrix_wechat.db.upgrade import upgrade_table
from mautrix_wechat.db.user import User
from mautrix_wechat.db.puppet import Puppet
from mautrix_wechat.db.portal import Portal
from mautrix_wechat.db.message import Message


def init(db: Database) -> None:
    for table in (User, Puppet, Portal, Message):
        table.db = db


__all__ = ["upgrade_table", "init", "User", "Puppet", "Portal", "Message",]