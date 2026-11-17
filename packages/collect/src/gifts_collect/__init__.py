import asyncio

from gifts_collect.providers.portals.client import PortalsAPI

DEVICE_MODEL = "gift_collect"
APP_VERSION = "2.3 K"
SYSTEM_VERSION = "android"

async def main():
    async with PortalsAPI() as c:
        collections = await c.collections()
        for collection in collections.collections:
            print(f"collection: {collection.name}, floor: {collection.floor_price}")
            
        actions = await c.actions()


def start() -> None:
    asyncio.run(main())
