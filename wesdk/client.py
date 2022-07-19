from asyncio import futures
import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from lxml import etree
from io import StringIO
from uuid import uuid4
from queue import Queue
from abc import ABCMeta, abstractmethod
from typing import Awaitable, Iterable, Optional, Union, Tuple
from collections import defaultdict
from dataclasses import asdict

import aiohttp
from dateutil import parser
from websockets import connect
from mautrix.util.logging import TraceLogger

from wesdk import query
from wesdk.image import ImageDecodeError, WechatImageDecoder
from wesdk.types import (
    ChatRoomNick,
    WechatID,
    WechatUser,
    TxtMessage,
    PicMessage,
    TxtCiteMessage,
    WechatUserDetail,
)


def register(q):
    def inner(func):
        func._register = q
        return func

    return inner


async def print_msg(_, msg):
    print(msg)


class ClientBase(ABCMeta):
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

    _contact_list: dict[WechatID, WechatUser]

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
        self.last_heart_beat = None
        self.wx_code = None
        self.wx_id = None
        self.wx_name = None
        self._ws = None
        self._contact_list = {}
        self._futures = {}
        self._pending_messages = Queue()
        self._communicate_task = None

    async def connect(self) -> None:
        if not self.session:
            self.session = aiohttp.ClientSession()

        # initial_connect = self.loop.create_future()
        self._communicate_task = self.loop.create_task(self._run_forever())
        # await initial_connect

    async def _run_forever(self) -> None:
        async with connect(f"ws://{self.ip}:{self.port}") as ws:
            while True:
                recv_task = asyncio.create_task(self._recv(ws))
                send_task = asyncio.create_task(self._send(ws))
                _, pending = await asyncio.wait(
                    [recv_task, send_task], return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()

    async def _recv(self, ws) -> None:
        msg = await ws.recv()
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

    async def _send(self, ws) -> None:
        while not self._pending_messages.empty():
            msg = self._pending_messages.get()
            if isinstance(msg, str):
                await ws.send(msg)
            elif isinstance(msg, asyncio.Future):
                await msg
            else:
                self.logger.warning(f"Unsupported message {msg} type: {type(msg)}")

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
        if self._communicate_task:
            self._communicate_task.cancel()
            self._communicate_task = None

    def getset_future(self, payload: any = None) -> Tuple[str, Awaitable]:
        msg_id = str(uuid4())
        future = self.loop.create_future()
        self._futures[msg_id] = (future, payload)
        return msg_id, future

    @register(query.HEART_BEAT)
    async def handle_heart_beat(self, msg) -> None:
        self.last_heart_beat = (
            parser.parse(msg.get("time")) if msg.get("time") else None
        )
        await self.on_heart_beat(msg)

    @register(query.PERSONAL_DETAIL)
    async def handle_personal_detail(self, msg) -> None:
        msg_id = msg.get("id")
        wechat_user_detail = WechatUserDetail(**msg.get("content", {}))
        future, _ = self._futures.pop(msg_id, (None, None))
        if future:
            future.set_result(
                wechat_user_detail if any(asdict(wechat_user_detail).values()) else None
            )

    @register(query.CHATROOM_MEMBER)
    async def handle_chatroom_member(self, msg) -> None:
        msg_id = msg.get("id")
        # TODO: future will break if not found
        future, room_id = self._futures.pop(msg_id, (None, None))
        for chat_room in msg.get("content", {}):
            if chat_room_id := chat_room.get("room_id"):
                if room_id and chat_room_id == room_id:
                    return future.set_result(
                        [WechatID(m) for m in chat_room.get("member")]
                    )
                elif WechatID(chat_room_id) in self._contact_list:
                    self._contact_list[WechatID(chat_room_id)].chat_room_members = [
                        WechatID(m) for m in chat_room.get("member")
                    ]
        future.set_result(None)

    @register(query.CHATROOM_MEMBER_NICK)
    async def handle_chatroom_member_nick(self, msg) -> None:
        msg_id = msg.get("id")
        chat_room_nick = ChatRoomNick(**msg.get("content", {}))
        future, _ = self._futures.pop(msg_id, (None, None))
        if future:
            future.set_result(
                chat_room_nick if any(asdict(chat_room_nick).values()) else None
            )

    @register(query.CHATROOM_MEMBER_NICK)
    async def handle_user_nick(self, msg) -> None:
        return await self.handle_chatroom_member_nick(msg)

    @register(query.PERSONAL_INFO)
    async def handle_personal_info(self, msg) -> None:
        msg_id = msg.get("id")
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
        future, _ = self._futures.pop(msg_id, (None, None))
        if future:
            future.set_result(
                WechatUser(
                    name=self.wx_name,
                    wxid=self.wx_id,
                    wxcode=self.wx_code,
                    headimg="",
                    remarks="",
                )
                if self.wx_id and self.wx_name
                else None
            )

    @register(query.USER_LIST)
    async def handle_user_list(self, msg) -> None:
        msg_id = msg.get("id")
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
        self.logger.debug(f"Received {count} contacts")
        future, _ = self._futures.pop(msg_id, (None, None))
        if future:
            future.set_result(self._contact_list.values())

    @register(query.AT_MSG)
    async def handle_at_msg(self, msg) -> None:
        await self.on_at_message(self, msg)

    @register(query.RECV_PIC_MSG)
    async def handle_recv_pic_msg(self, msg) -> None:
        if content := msg.get("content"):
            try:
                if "WECHAT_FILES_DIR" not in os.environ:
                    raise ImageDecodeError("WECHAT_FILES_DIR not set")
                wechat_files_dir = os.environ["WECHAT_FILES_DIR"]
                parsed = etree.fromstring(content.get('content'))
                keys = parsed.xpath("//img/@aeskey")
                if not keys:
                    raise ImageDecodeError("No aeskey found")
                key = keys[0]

                # Try to find full image first
                use_thumb = False
                img_file = Path(wechat_files_dir).joinpath(content.get('detail').replace('\\', '/'))
                if not img_file.exists():
                    use_thumb = True
                    img_file = Path(wechat_files_dir).joinpath(content.get('thumb').replace('\\', '/'))
                if not img_file.exists():
                    raise ImageDecodeError("No .dat file found")
                
                await self.on_pic_message(
                    PicMessage(
                        id=msg.get("id"),
                        source=WechatID(content.get("id1")),
                        sender=WechatID(
                            content.get("id2") if content.get("id2") else content.get("id1")
                        ),
                        time=parser.parse(msg.get("time")),
                        msg='thumb' if use_thumb else None,
                        path=Path(WechatImageDecoder.decode(str(img_file.absolute()))).absolute()
                    )
                )
            except Exception as e:
                await self.on_pic_message(
                    PicMessage(
                        id=msg.get("id"),
                        source=WechatID(content.get("id1")),
                        sender=WechatID(
                            content.get("id2") if content.get("id2") else content.get("id1")
                        ),
                        msg=str(e),
                        path=None))
        else:
            self.logger.warning(f"Received malformatted pic message: {msg}")

    @register(query.RECV_TXT_MSG)
    async def handle_recv_txt_msg(self, msg) -> None:
        await self.on_txt_message(
            TxtMessage(
                id=msg.get("id"),
                source=WechatID(msg.get("wxid")),
                sender=WechatID(msg.get("id1") if msg.get("id1") else msg.get("wxid")),
                time=parser.parse(msg.get("time")),
                content=msg.get("content"),
            )
        )

    @register(query.RECV_TXT_CITE_MSG)
    async def handle_recv_txt_cite_msg(self, msg) -> None:
        if content := msg.get("content"):
            await self.on_txt_cite_message(
                TxtCiteMessage(
                    id=msg.get("id"),
                    source=WechatID(content.get("id1")),
                    sender=WechatID(
                        content.get("id2") if content.get("id2") else content.get("id1")
                    ),
                    time=parser.parse(msg.get("time")),
                    content=content.get("content"),
                )
            )
        else:
            self.logger.warning(f"Received malformatted txt cite message: {msg}")

    async def get_personal_info(self) -> Optional[WechatUser]:
        msg_id, future = self.getset_future()
        self._pending_messages.put(query.get_personal_info(msg_id))
        return await future

    async def get_personal_detail(
        self, wxid: str | WechatID
    ) -> Optional[WechatUserDetail]:
        msg_id, future = self.getset_future()
        self._pending_messages.put(query.get_personal_detail(wxid, msg_id))
        return await future

    async def get_contact_list(self) -> Iterable[WechatUser]:
        msg_id, future = self.getset_future()
        self._pending_messages.put(query.get_contact_list(msg_id))
        return await future

    async def get_chatroom_member(
        self, room_id: WechatID
    ) -> list[WechatID]:
        msg_id, future = self.getset_future(room_id)
        self._pending_messages.put(
            query.get_chatroom_member(roomid=room_id or "null", msg_id=msg_id)
        )
        return await future

    async def fetch_chatroom_members(self) -> None:
        msg_id, future = self.getset_future(None)
        self._pending_messages.put(
            query.get_chatroom_member("null", msg_id=msg_id)
        )
        return await future

    async def get_chatroom_member_nick(
        self, room_id: WechatID, wxid: WechatID
    ) -> Optional[ChatRoomNick]:
        msg_id, future = self.getset_future()
        self._pending_messages.put(query.get_chatroom_member_nick("null", wxid, msg_id))
        return await future

    async def get_user_nick(self, wxid: WechatID) -> Optional[ChatRoomNick]:
        msg_id, future = self.getset_future()
        self._pending_messages.put(query.get_user_nick(wxid, msg_id))
        return await future

    async def get_user(self, wxid: WechatID) -> WechatUser:
        if wxid in self._contact_list:
            return self._contact_list[wxid]
        user_nick = await self.get_user_nick(wxid)
        return WechatUser("", user_nick.nick, "", "", wxid)

    async def on_heart_beat(self, msg) -> None:
        self.logger.trace(f"Received heart beat: {self.last_heart_beat}")

    async def on_chatroom_member(self, msg) -> None:
        print(f"Received chatroom member: {msg}")

    async def on_chatroom_member_nick(self, msg) -> None:
        print(f"Received chatroom member nick: {msg}")

    @abstractmethod
    async def on_at_message(self, msg) -> None:
        print(f"Received at message: {msg}")

    @abstractmethod
    async def on_txt_message(self, msg: TxtMessage) -> None:
        print(f"Received txt message: {msg}")

    @abstractmethod
    async def on_pic_message(self, msg: PicMessage) -> None:
        print(f"Received pic message: {msg}")

    @abstractmethod
    async def on_txt_cite_message(self, msg: TxtCiteMessage) -> None:
        print(f"Received txt cite message: {msg}")


class WechatHandler(WechatClient):
    async def on_heart_beat(self, msg) -> None:
        print(f"Received heart beat: {self.last_heart_beat}")

    async def on_at_message(self, msg) -> None:
        print(f"Received at message: {msg}")

    async def on_txt_message(self, msg: TxtMessage) -> None:
        print(f"Received txt message: {msg}")
        print(await self.get_user(msg.sender))

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


async def test(we: WechatClient):
    info = await we.get_personal_info()
    await we.get_contact_list()
    print(info)
    for user in await we.get_contact_list():
        if user.is_chatroom:
            print(user)
            members  = await we.get_chatroom_member(user.wxid)
            nicks = await asyncio.gather(*[we.get_chatroom_member_nick(user.wxid, m) for m in members])
            print(nicks)


if __name__ == "__main__":
    logger = TraceLogger("client")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    loop = asyncio.new_event_loop()
    we = WechatHandler(logger=logger, loop=loop)
    loop.create_task(we.connect())
    loop.create_task(test(we))
    loop.run_forever()
