from typing import Any

from mautrix.bridge import Bridge
from mautrix.bridge.state_store.asyncpg import PgBridgeStateStore
from mautrix.types import RoomID, UserID
from mautrix.util.async_db import Database
from mautrix_wechat.version import version
from mautrix_wechat.config import Config
from mautrix_wechat.db import upgrade_table, init as init_db
from mautrix_wechat.matrix import MatrixHandler
from mautrix_wechat.wechat import WechatHandler
from mautrix_wechat.user import User
from mautrix_wechat.portal import Portal
from mautrix_wechat.puppet import Puppet


class WechatBridge(Bridge):
    module = "mautrix_wechat"
    name = "mautrix-wechat"
    command = "python -m mautrix-wechat"
    description = "A Matrix-Wechat puppeting bridge."
    repo_url = "https://github.com/leishi1313/mautrix-wechat"
    real_user_content_key = "net.maunium.wechat.puppet"
    version = version
    markdown_version = version
    config_class = Config
    matrix_class = MatrixHandler
    upgrade_table = upgrade_table

    db: Database
    matrix: MatrixHandler
    wechat: WechatHandler
    config: Config
    state_store: PgBridgeStateStore


    def prepare_db(self) -> None:
        super().prepare_db()
        init_db(self.db)

    def prepare_bridge(self) -> None:
        super().prepare_bridge()
        # self.provisioning_api = ProvisioningAPI(cfg["shared_secret"])
        # self.az.app.add_subapp(cfg["prefix"], self.provisioning_api.app)
        self.wechat = WechatHandler(self)

    async def resend_bridge_info(self) -> None:
        self.config["bridge.resend_bridge_info"] = False
        self.config.save()
        self.log.info("Re-sending bridge info state event to all portals")
        async for portal in Portal.all():
            await portal.update_bridge_info()
        self.log.info("Finished re-sending bridge info state events")

    async def start(self) -> None:
        User.init_cls(self)
        Portal.init_cls(self)
        Puppet.init_cls(self)
        if self.config["bridge.resend_bridge_info"]:
            self.add_startup_actions(self.resend_bridge_info())
        self.add_startup_actions(self.wechat.start())

        await super().start()

    def prepare_stop(self) -> None:
        self.add_shutdown_actions(self.wechat.stop())
        # self.add_shutdown_actions(user.stop() for user in User.by_mxid.values())
        for puppet in Puppet.by_custom_mxid.values():
            puppet.stop()

    async def get_portal(self, room_id: RoomID) -> Portal:
        return await Portal.get_by_mxid(room_id)

    async def get_puppet(self, user_id: UserID, create: bool = False) -> Puppet:
        return await Puppet.get_by_mxid(user_id, create=create)

    async def get_double_puppet(self, user_id: UserID) -> Puppet:
        return await Puppet.get_by_custom_mxid(user_id)

    async def get_user(self, user_id: UserID, create: bool = True) -> User:
        return await User.get_by_mxid(user_id, create=create)

    def is_bridge_ghost(self, user_id: UserID) -> bool:
        return bool(Puppet.get_id_from_mxid(user_id))

    async def count_logged_in_users(self) -> int:
        return len([user for user in User.by_mxid.values if user.mxid])

    async def manhole_global_namespace(self, user_id: UserID) -> dict[str, Any]:
        return {
            **await super().manhole_global_namespace(user_id),
            "User": User,
            "Portal": Portal,
            "Puppet": Puppet,
        }


WechatBridge().run()