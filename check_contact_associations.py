
import asyncio
import json

from app.clients.hubspot import HubSpotClient


async def main():
    client = HubSpotClient()
    try:
        result = await client.get_contact_companies("577752633026")
        print(json.dumps(result, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
