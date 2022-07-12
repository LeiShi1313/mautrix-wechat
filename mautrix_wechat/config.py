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
        ]

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        super().do_update(helper)
        copy, copy_dict, base = helper

        copy("homeserver.asmux")

        copy("wechat.boxes")

        copy("metrics.enabled")
        copy("metrics.listen_port")

        copy("bridge.username_template")
        copy("bridge.displayname_template")
        copy("bridge.command_prefix")

        copy("bridge.initial_chat_sync")
        copy("bridge.invite_own_puppet_to_pm")
        copy("bridge.sync_with_custom_puppets")
        copy("bridge.sync_direct_chat_list")
        copy("bridge.double_puppet_server_map")
        copy("bridge.double_puppet_allow_discovery")
        if "bridge.login_shared_secret" in self:
            base["bridge.login_shared_secret_map"] = {
                base["homeserver.domain"]: self["bridge.login_shared_secret"]
            }
        else:
            copy("bridge.login_shared_secret_map")
        copy("bridge.update_avatar_initial_sync")
        copy("bridge.encryption.allow")
        copy("bridge.encryption.default")
        copy("bridge.encryption.key_sharing.allow")
        copy("bridge.encryption.key_sharing.require_cross_signing")
        copy("bridge.encryption.key_sharing.require_verification")
        copy("bridge.delivery_receipts")
        copy("bridge.delivery_error_reports")
        copy("bridge.message_status_events")
        copy("bridge.federate_rooms")
        copy("bridge.backfill.invite_own_puppet")
        copy("bridge.backfill.initial_thread_limit")
        copy("bridge.backfill.initial_thread_reply_limit")
        copy("bridge.backfill.initial_nonthread_limit")
        copy("bridge.backfill.missed_event_limit")
        copy("bridge.backfill.missed_event_page_size")
        copy("bridge.backfill.disable_notifications")
        copy("bridge.resend_bridge_info")
        copy("bridge.unimportant_bridge_notices")
        copy("bridge.disable_bridge_notices")

        copy("bridge.provisioning.prefix")
        if "bridge.web.auth.shared_secret" in self:
            base["bridge.provisioning.shared_secret"] = self["bridge.web.auth.shared_secret"]
        if self["bridge.provisioning.shared_secret"] == "generate":
            base["bridge.provisioning.shared_secret"] = self._new_token()
        else:
            copy("bridge.provisioning.shared_secret")

        copy_dict("bridge.permissions")

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