from typing import List, Union, TYPE_CHECKING

from mautrix.bridge import BaseMatrixHandler
from mautrix.types import (Event, ReactionEvent, MessageEvent, StateEvent, EncryptedEvent, RoomID,
                           EventID, UserID, ReactionEventContent, RelationType, EventType,
                           ReceiptEvent, TypingEvent, PresenceEvent, RedactionEvent)

from mautrix_wechat.db import Message as DBMessage
from mautrix_wechat import commands as com, puppet as pu, portal as po, user as u

if TYPE_CHECKING:
    from .__main__ import WechatBridge


class MatrixHandler(BaseMatrixHandler):
    pass