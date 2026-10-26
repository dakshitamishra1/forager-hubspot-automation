import asyncio

from app.clients.hubspot import HubSpotClient


async def main() -> None:
    client = HubSpotClient()

    try:
        result = await client.list_companies(limit=5)

        print("HubSpot client is working.")
        print("Companies returned:", len(result.get("results", [])))

        for company in result.get("results", []):
            print(
                "Company ID:",
                company["id"],
                "| Properties:",
                company.get("properties", {}),
            )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())