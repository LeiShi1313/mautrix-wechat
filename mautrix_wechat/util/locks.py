from asyncio import Lock
from collections import defaultdict

from wesdk.types import WechatID


class FakeLock:
    async def __aenter__(self) -> None:
        pass

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass


class PortalSendLock:
    _send_locks: dict[int, Lock]
    _noop_lock: Lock = FakeLock()

    def __init__(self) -> None:
        self._send_locks = {}

    def __call__(self, wxid: WechatID, required: bool = True) -> Lock:
        if wxid is None and required:
            raise ValueError("Required send lock for none id")
        try:
            return self._send_locks[wxid]
        except KeyError:
            return self._send_locks.setdefault(wxid, Lock()) if required else self._noop_lock
