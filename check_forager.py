
import asyncio
import httpx

from app.clients.forager import ForagerClient


async def main() -> None:
    client = ForagerClient()

    try:
        result = await client.search_organizations(
            organization_ids=[12988797],
            page=0,
        )

        organizations = result.get("search_results", [])

        print("Forager API request successful.")
        print("Total results:", result.get("total_search_results"))
        print("Organizations returned:", len(organizations))

        for org in organizations:
            linkedin = org.get("linkedin_info") or {}
            finance = org.get("finance_info") or {}
            industry = linkedin.get("industry") or {}
            addresses = org.get("addresses") or []

            print({
                "id": org.get("id"),
                "name": org.get("name"),
                "domain": org.get("domain"),
                "website": org.get("website"),
                "linkedin_url": linkedin.get("public_profile_url"),
                "description": org.get("description"),
                "employees_range": org.get("employees_range"),
                "employees_amount": org.get("employees_amount"),
                "revenue": finance.get("revenue"),
                "industry": industry.get("name"),
                "addresses": [
                    {
                        "city": address.get("city"),
                        "state": address.get("state"),
                        "country": address.get("country"),
                    }
                    for address in addresses
                ],
            })

    except httpx.HTTPStatusError as exc:
        print("HTTP status:", exc.response.status_code)
        print("API error:", exc.response.text[:1000])

    except httpx.RequestError as exc:
        print("Network error:", type(exc).__name__)

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
