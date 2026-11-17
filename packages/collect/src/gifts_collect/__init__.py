import asyncio
import sys

from gifts_collect.auth_ui import AuthCancelled, AuthError, console, ensure_session
from gifts_collect.config import API_HASH, API_ID, APP_VERSION, DEVICE_MODEL, SYSTEM_VERSION
from gifts_collect.providers.portals.client import PortalsAPI
from gifts_collect.providers.portals.telegram_auth import telegram_provider


async def main():
    session_string = await ensure_session()

    async with PortalsAPI(
        auth_provider=telegram_provider(
            API_ID,
            API_HASH,
            session_string,
            device_model=DEVICE_MODEL,
            app_version=APP_VERSION,
            system_version=SYSTEM_VERSION,
        )
    ) as c:
        collections = await c.collections()
        for collection in collections.collections:
            print(f"collection: {collection.name}, floor: {collection.floor_price}")

        actions = await c.actions(action_types=['buy', 'sell'])
        for action in actions.actions:
            print(f"action: {action.type} {action.nft.name} {action.amount}")


def start() -> None:
    try:
        asyncio.run(main())
    except AuthCancelled:
        sys.exit(130)
    except AuthError as e:
        console.print(f"[bold red]✘[/] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)