from typing import cast
from urllib.parse import parse_qs, urlparse

from pyrogram import Client as TgClient
from pyrogram import enums
from pyrogram.raw.base.input_bot_app import InputBotApp
from pyrogram.raw.base.input_peer import InputPeer
from pyrogram.raw.base.input_user import InputUser as BaseInputUser
from pyrogram.raw.functions.messages.request_app_web_view import RequestAppWebView
from pyrogram.raw.types.input_bot_app_short_name import InputBotAppShortName
from pyrogram.raw.types.input_peer_user import InputPeerUser
from pyrogram.raw.types.input_user import InputUser
from pyrogram.raw.types.web_view_result_url import WebViewResultUrl

from .client import AuthProvider
from .consts import TELEGRAM_APP_SHORT_NAME, TELEGRAM_BOT_USERNAME


async def get_init_data(tg: TgClient) -> str:
    peer = await tg.resolve_peer(TELEGRAM_BOT_USERNAME)
    if not isinstance(peer, InputPeerUser):
        raise RuntimeError("invalid telegram bot username")

    bot = InputUser(user_id=peer.user_id, access_hash=peer.access_hash)
    app = InputBotAppShortName(
        bot_id=cast(BaseInputUser, bot),
        short_name=TELEGRAM_APP_SHORT_NAME,
    )
    result = cast(
        WebViewResultUrl,
        await tg.invoke(
            RequestAppWebView(
                peer=cast(InputPeer, peer),
                app=cast(InputBotApp, app),
                platform="webk",
            )
        ),
    )
    return parse_qs(urlparse(result.url).fragment)["tgWebAppData"][0]


def telegram_provider(
    api_id: int,
    api_hash: str,
    session_string: str,
    *,
    device_model: str = "",
    app_version: str = "",
    system_version: str = "",
) -> AuthProvider:
    async def provider() -> str:
        async with TgClient(
            "tg",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True,
            device_model=device_model,
            app_version=app_version,
            system_version=system_version,
            client_platform=enums.ClientPlatform.WEB,
            lang_code="en",
            system_lang_code="en",
        ) as tg:
            return await get_init_data(tg)

    return provider
