
from gifts_collect.providers.portals import Client
import asyncio

async def main():
    async with Client() as c:
        collections = await c.collections()
        print(f"collections: {collections}")

def start() -> None:
    asyncio.run(main())