
import asyncio

from app.clients.hubspot import HubSpotClient


async def main():
    client = HubSpotClient()

    try:
        response = await client._client.post(
            "/crm/v3/objects/contacts/search",
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "hs_linkedin_url",
                                "operator": "EQ",
                                "value": "https://www.linkedin.com/in/test-profile/",
                            }
                        ]
                    }
                ],
                "properties": [
                    "firstname",
                    "lastname",
                    "jobtitle",
                    "hs_linkedin_url",
                ],
                "limit": 10,
            },
        )

        print("HTTP status:", response.status_code)
        print(response.text[:1500])
        response.raise_for_status()

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
