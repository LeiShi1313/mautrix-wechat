import os
from typing import Any, List, NamedTuple

from mautrix.types import UserID
from mautrix.client import Client
from mautrix.bridge.config import (BaseBridgeConfig, ConfigUpdateHelper, ForbiddenDefault)

Permissions = NamedTuple("Permissions", user=bool, admin=bool, level=str)

class Config(BaseBridgeConfig):
    def __getitem__(self, key: str) -> Any:
        try:
            return os.environ[f"MAUTRIX_WECHAT_{key.replace('.', '_').upper()}"]
        except KeyError:
            return super().__getitem__(key)

    @property
    def forbidden_defaults(self) -> List[ForbiddenDefault]:
        return [
            *super().forbidden_defaults,
            ForbiddenDefault("homeserver.address", "https://example.com"),
            ForbiddenDefault("homeserver.domain", "example.com"),
            ForbiddenDefault("bridge.permissions", "example.com"),
            ForbiddenDefault("appservice.database", "postgres://username:password@hostname/db"),
        ]

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        super().do_update(helper)
        copy, copy_dict, base = helper

    def _get_permissions(self, key: str) -> Permissions:
        level = self["bridge.permissions"].get(key, "")
        admin = level == "admin"
        user = level == "user" or admin
        return Permissions(user, admin, level)

    def get_permissions(self, mxid: UserID) -> Permissions:
        permissions = self["bridge.permissions"]
        if mxid in permissions:
            return self._get_permissions(mxid)

        _, homeserver = Client.parse_user_id(mxid)
        if homeserver in permissions:
            return self._get_permissions(homeserver)

        return self._get_permissions("*")