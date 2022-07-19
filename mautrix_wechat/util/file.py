
from typing import AsyncIterable

import aiohttp
from yarl import URL
from mautrix.util.magic import mimetype
from mautrix.types import ContentURI
from mautrix_wechat.config import Config
from mautrix.appservice import IntentAPI


async def upload_file(
    data: bytes | bytearray | AsyncIterable[bytes], intent: IntentAPI, config: Config, filename: str | None = None
) -> ContentURI:
    mime = mimetype(data)
    return await intent.upload_media(
            data,
            mime_type=mime,
            filename=filename,
            async_upload=config["homeserver.async_media"],
        )

async def download_and_upload_file(
    url: str, intent: IntentAPI, config: Config, filename: str | None = None
) -> ContentURI:
    async with aiohttp.ClientSession() as session:
        resp = await session.get(URL(url))
        data = await resp.read()
    mime = mimetype(data)
    return await intent.upload_media(
            data,
            mime_type=mime,
            filename=filename,
            async_upload=config["homeserver.async_media"],
        )