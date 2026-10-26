
import httpx

from app.config import settings


class HubSpotClient:
    """Client for interacting with the HubSpot CRM API."""

    BASE_URL = "https://api.hubapi.com"

    def __init__(self) -> None:
        if not settings.hubspot_access_token:
            raise ValueError("HUBSPOT_ACCESS_TOKEN is not configured")

        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": (
                    f"Bearer {settings.hubspot_access_token}"
                ),
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def list_companies(self, limit: int = 10) -> dict:
        response = await self._client.get(
            "/crm/v3/objects/companies",
            params={"limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def get_company(self, company_id: str) -> dict:
        response = await self._client.get(
            f"/crm/v3/objects/companies/{company_id}",
            params={
                "properties": [
                    "name",
                    "domain",
                    "description",
                    "numberofemployees",
                    "annualrevenue",
                ]
            },
        )
        response.raise_for_status()
        return response.json()


    
    async def search_companies_by_domain(self, domain: str) -> dict:
        response = await self._client.post(
            "/crm/v3/objects/companies/search",
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "domain",
                                "operator": "EQ",
                                "value": domain,
                            }
                        ]
                    }
                ],
                "properties": [
                    "name",
                    "domain",
                    "description",
                    "numberofemployees",
                    "annualrevenue",
                ],
                "limit": 10,
            },
        )
        response.raise_for_status()
        return response.json()


    
    async def create_company(self, properties: dict[str, str]) -> dict:
        response = await self._client.post(
            "/crm/v3/objects/companies",
            json={"properties": properties},
        )
        response.raise_for_status()
        return response.json()
    async def update_company(
        self,
        company_id: str,
        properties: dict[str, str],
    ) -> dict:
        """Update properties of an existing HubSpot company."""
        response = await self._client.patch(
            f"/crm/v3/objects/companies/{company_id}",
            json={"properties": properties},
        )
        response.raise_for_status()
        return response.json()
    async def search_contacts_by_linkedin(self, linkedin_url: str) -> dict:
        response = await self._client.post(
            "/crm/v3/objects/contacts/search",
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "hs_linkedin_url",
                                "operator": "EQ",
                                "value": linkedin_url,
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
        if response.is_error:
            raise RuntimeError(
                f"HubSpot contact search failed: "
                f"HTTP {response.status_code}: {response.text}"
            )
        return response.json()


    async def create_contact(
        self, properties: dict[str, str]
    ) -> dict:
        response = await self._client.post(
            "/crm/v3/objects/contacts",
            json={"properties": properties},
        )
        response.raise_for_status()
        return response.json()

    async def associate_contact_with_company(
        self, contact_id: str, company_id: str
    ) -> None:
        response = await self._client.put(
            f"/crm/v4/objects/contacts/{contact_id}"
            f"/associations/default/companies/{company_id}",
        )
        response.raise_for_status()

    
    async def get_contact(self, contact_id: str) -> dict:
        response = await self._client.get(
            f"/crm/v3/objects/contacts/{contact_id}",
            params={
                "properties": [
                    "firstname",
                    "lastname",
                    "email",
                    "jobtitle",
                    "hs_linkedin_url",
                    "company",
                    "city",
                    "state",
                    "country",
                ]
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_contact_companies(self, contact_id: str) -> dict:
        response = await self._client.get(
            f"/crm/v4/objects/contacts/{contact_id}/associations/companies"
        )
        response.raise_for_status()
        return response.json()

    async def update_contact(
        self, contact_id: str, properties: dict[str, str]
    ) -> dict:
        response = await self._client.patch(
            f"/crm/v3/objects/contacts/{contact_id}",
            json={"properties": properties},
        )
        response.raise_for_status()
        return response.json()


    async def close(self) -> None:
        await self._client.aclose()
