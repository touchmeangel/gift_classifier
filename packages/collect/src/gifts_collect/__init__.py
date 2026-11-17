
from gifts_collect.providers.portals import Client
import asyncio

async def main():
    async with Client(cf_clearance="CmXMTTTQ3GWm40KY_LuXWIzG1hJ3Hr-T6GsNTizsVHW0Tv4h40mw0UWXQUOWcpvDCjngJkqZmmHtonEMYN6XafeVc0rL5izo81X6gRnFYkfB23dlRP8KNHY1S2FiYcvk4VPKLG_5O-RALyZ57MlElKwUm7kpLisB-yVu3zHT6Wl7Y5QwAOM_izyynzt-4SyiizZ8JPOTrrGM3U4RIMxromuTW5-BJ22N-uzoQapEoOILGF7HRFZl-GcKAvAsYgVAIex0ExN2p00kU5Q4H3bwmzHEf09f_kAhuSaQFpA70pJDzxFMhhm6hxw") as c:
        collections = await c.collections()
        print(f"collections: {collections}")

def start() -> None:
    asyncio.run(main())