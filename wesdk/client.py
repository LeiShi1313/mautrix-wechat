import sys
import json
import asyncio
import logging
from queue import Queue
from typing import Optional, Union
from collections import defaultdict

import aiohttp
from dateutil import parser
from websockets import connect
from mautrix.util.logging import TraceLogger

from wesdk import query
from wesdk.types import WechatID, WechatUser, TxtMessage, PicMessage, TxtCiteMessage


def register(q):
    def inner(func):
        func._register = q
        return func

    return inner


async def print_msg(_, msg):
    print(msg)


class ClientBase(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, "handler_registry"):
            cls.handler_registry = defaultdict(lambda: print_msg)
        for key, val in attrs.items():
            query = getattr(val, "_register", None)
            if query is not None:
                cls.handler_registry[query] = val


class WechatClient(metaclass=ClientBase):
    log: TraceLogger
    loop: asyncio.AbstractEventLoop
    session: aiohttp.ClientSession
    handler_registry: dict

    def __init__(
        self,
        ip: str = "127.0.0.1",
        port: int = 5555,
        logger: Optional[TraceLogger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.ip = ip
        self.port = port
        self.logger = logger or logging.getLogger("wesdk")
        self.loop = loop or asyncio.get_event_loop()
        self.session = None
        self.logged_in = False
        self.conn = None
        self.last_heart_beat = None
        self.wx_code = None
        self.wx_id = None
        self.wx_name = None
        self._ws = None
        self._contact_list = {}
        self._pending_messages = Queue()
        self._pending_messages.put(query.get_personal_info())
        self._pending_messages.put(query.get_contact_list())
        # self._pending_messages.put(query.get_chatroom_member('wxid_v11uy95lmdjh22'))
        self._communicate_task = None

    async def connect(self) -> None:
        if not self.conn:
            self.conn = connect(f"ws://{self.ip}:{self.port}")
        if not self.session:
            self.session = aiohttp.ClientSession()

        # initial_connect = self.loop.create_future()
        self._communicate_task = self.loop.create_task(self._run_forever())
        # await initial_connect

    async def _run_forever(
        self, initial_connect: Optional[asyncio.Future] = None
    ) -> None:
        async with self.conn as ws:
            self.loop.create_task(self._send_pending_messages(ws))
            async for msg in ws:
                self.loop.create_task(self._send_pending_messages(ws))

                msg = json.loads(msg)
                # TODO: maybe recursive loads the response
                if "content" in msg and isinstance(msg["content"], str):
                    try:
                        msg["content"] = json.loads(msg["content"])
                    except:
                        pass
                resp_type = msg.get("type")
                try:
                    self.loop.create_task(self.handler_registry[resp_type](self, msg))
                except Exception as e:
                    self.logger.exception(e)
                    continue
                # self.loop.create_task(self.handler_registry.get(resp_type)(self, msg))

    def retrieve_login_info(self) -> None:
        self._pending_messages.put(query.get_personal_info())
        self._pending_messages.put(query.get_contact_list())

    async def _send_pending_messages(self, ws) -> None:
        while not self._pending_messages.empty():
            msg = self._pending_messages.get()
            if isinstance(msg, str):
                await ws.send(msg)
            elif isinstance(msg, asyncio.Future):
                await msg

    async def send_http(self, uri: str, data: Union[dict, str, bytes]):
        if isinstance(data, str) or isinstance(data, bytes):
            data = json.loads(data)
        base_data = {
            "id": query.uuid(),
            "type": "null",
            "roomid": "null",
            "wxid": "null",
            "content": "null",
            "nickname": "null",
            "ext": "null",
        }
        base_data.update(data)
        url = f"http://{self.ip}:{self.port}/{uri}"
        resp = await self.session.post(url, json={"para": base_data}, timeout=5)
        data = json.loads(await resp.text())
        if "content" in data and isinstance(data["content"], str):
            try:
                data["content"] = json.loads(data["content"])
            except Exception as e:
                pass
        return data
        # # 某些版本获取不到群昵称，需要从联系人里取
        # if rsp.get('type', 0) == query.CHATROOM_MEMBER_NICK \
        #     and not rsp['content'].get('nick', ''):
        #     if rsp['content']['wxid'] not in ['ROOT', 'null']:
        #         rsp['content']['nick'] = self.contact_list.get(rsp['content']['wxid'], {}).get('name', '')
        #     elif rsp['content']['roomid'] not in ['null']:
        #         rsp['content']['nick'] = self.contact_list.get(rsp['content']['roomid'], {}).get('name', '')

    async def send_msg(
        self,
        msg,
        wxid: str = "null",
        roomid: str = "null",
        nickname: str = "null",
        force_type=None,
    ):
        return await self.send_http(
            "/api/sendtxtmsg", query.send_msg(msg, wxid, roomid, nickname, force_type)
        )

    async def disconnect(self) -> None:
        if self.conn:
            self.conn.close()
        if self._communicate_task:
            self._communicate_task.cancel()
            self._communicate_task = None

    @register(query.HEART_BEAT)
    async def handle_heart_beat(self, msg) -> None:
        self.last_heart_beat = (
            parser.parse(msg.get("time")) if msg.get("time") else None
        )
        self.logger.debug(f"Received heart beat: {self.last_heart_beat}")

    @register(query.PERSONAL_INFO)
    async def handle_personal_info(self, msg) -> None:
        self.logger.trace(msg)
        self.wx_id = msg.get("content", {}).get("wx_id")
        self.wx_code = msg.get("content", {}).get("wx_code")
        self.wx_name = msg.get("content", {}).get("wx_name")
        if self.wx_id:
            self.logged_in = True
            self.logger.info(f"User {self.wx_name} ({self.wx_id}) logged in.")
        elif self.wx_name:
            self.logged_in = False
            self.logger.info(
                f"User {self.wx_name} needs approve to re-logged in, please go to https://{self.ip}:8081/vnc.html"
            )
        else:
            self.logged_in = False
            self.logger.info(
                f"No account logged in, please go to https://{self.ip}:8081/vnc.html to log in."
            )
        await self.on_personal_info(
            WechatUser(name=self.wx_name, wxid=self.wx_id, wxcode=self.wx_code, headimg='', remarks='')
            if self.wx_id and self.wx_name
            else None
        )

    @register(query.USER_LIST)
    async def handle_user_list(self, msg) -> None:
        self.logger.trace(msg)
        count = 0
        for user in msg.get("content", []):
            if wxid := user.get("wxid"):
                count += 1
                self._contact_list[WechatID(wxid)] = WechatUser(
                    headimg=user.get("headimg"),
                    name=user.get("name"),
                    remarks=user.get("remarks"),
                    wxcode=user.get("wxcode"),
                    wxid=WechatID(user.get("wxid")),
                )
        self.logger.info(f"Received {count} contacts")

    @register(query.AT_MSG)
    async def handle_at_msg(self, msg) -> None:
        await self.on_message(self, msg)

    @register(query.RECV_PIC_MSG)
    async def handle_recv_pic_msg(self, msg) -> None:
        if content := msg.get("content"):
            await self.on_pic_message(
                PicMessage(
                    source=WechatID(content.get("id1")),
                    user=WechatID(
                        content.get("id2") if content.get("id2") else content.get("id1")
                    ),
                    time=parser.parse(msg.get("time")),
                    content=content.get("content"),
                )
            )
        else:
            self.logger.warning(f"Received malformatted pic message: {msg}")

    @register(query.RECV_TXT_MSG)
    async def handle_recv_txt_msg(self, msg) -> None:
        await self.on_txt_message(
            TxtMessage(
                source=WechatID(msg.get("wxid")),
                user=WechatID(msg.get("id1") if msg.get("id1") else msg.get("wxid")),
                time=parser.parse(msg.get("time")),
                content=msg.get("content"),
            )
        )

    @register(query.RECV_TXT_CITE_MSG)
    async def handle_recv_txt_cite_msg(self, msg) -> None:
        if content := msg.get("content"):
            await self.on_txt_cite_message(
                TxtCiteMessage(
                    source=WechatID(content.get("id1")),
                    user=WechatID(
                        content.get("id2") if content.get("id2") else content.get("id1")
                    ),
                    time=parser.parse(msg.get("time")),
                    content=content.get("content"),
                )
            )
        else:
            self.logger.warning(f"Received malformatted txt cite message: {msg}")

    async def on_personal_info(self, source: Optional[WechatUser]) -> None:
        print(f"Received personal info: {source}")

    async def on_at_message(self, msg) -> None:
        print(f"Received at message: {msg}")

    async def on_txt_message(self, msg: TxtMessage) -> None:
        print(f"Received txt message: {msg}")

    async def on_pic_message(self, msg: PicMessage) -> None:
        print(f"Received pic message: {msg}")

    async def on_txt_cite_message(self, msg: TxtCiteMessage) -> None:
        print(f"Received txt cite message: {msg}")


async def send(we: WechatClient):
    while True:
        await we.send_msg(
            "https://dl3.pushbulletusercontent.com/vlM7SVMh04Xhc4850EfQfzzrrddqmyn9/mmexport1655323967706.jpg",
            "liber_13",
        )
        await asyncio.sleep(5)


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    loop = asyncio.get_event_loop()
    we = WechatClient(logger=logger, loop=loop)
    loop.create_task(we.connect())
    # loop.create_task(send(we))
    loop.run_forever()
