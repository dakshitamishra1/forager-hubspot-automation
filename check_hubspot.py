import asyncio

import httpx

from app.config import settings


async def main() -> None:
    token = settings.hubspot_access_token

    if not token:
        print("ERROR: HUBSPOT_ACCESS_TOKEN is missing from .env")
        return

    url = "https://api.hubapi.com/crm/v3/objects/companies"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    params = {"limit": 1}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            url,
            headers=headers,
            params=params,
        )

    if response.is_success:
        data = response.json()
        print("HubSpot authentication successful!")
        print("Companies returned:", len(data.get("results", [])))
    else:
        print("HubSpot API request failed.")
        print("HTTP status:", response.status_code)
        print("Response:", response.text[:500])


if __name__ == "__main__":
    asyncio.run(main())