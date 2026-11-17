
from gifts_collect.providers.portals.client import Client
import asyncio

async def main():
    async with Client() as c:
        collections = await c.collections()
        for collection in collections.collections:
            print(f"collection: {collection.name}, floor: {collection.floor_price}")

def start() -> None:
    asyncio.run(main())