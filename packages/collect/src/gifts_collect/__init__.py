import asyncio

from gifts_collect.providers.portals.client import Client


async def main():
    async with Client() as c:
        collections = await c.collections()
        for collection in collections.collections:
            print(f"collection: {collection.name}, floor: {collection.floor_price}")
            
        actions = await c.actions()


def start() -> None:
    asyncio.run(main())
