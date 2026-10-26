
import asyncio

import httpx

from app.clients.hubspot import HubSpotClient


async def main() -> None:
    client = HubSpotClient()

    try:
        result = await client.search_companies_by_domain("openai.com")

        companies = result.get("results", [])
        print("HubSpot company search successful.")
        print("Matching companies:", len(companies))

        for company in companies:
            print({
                "id": company.get("id"),
                "properties": company.get("properties", {}),
            })

    except httpx.HTTPStatusError as exc:
        print("HTTP status:", exc.response.status_code)
        print("HubSpot error:", exc.response.text[:1000])

    except httpx.RequestError as exc:
        print("Network error:", type(exc).__name__)

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
