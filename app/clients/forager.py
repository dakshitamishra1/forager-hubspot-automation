
import httpx

from app.config import settings


class ForagerClient:
    BASE_URL = "https://api-v2.forager.ai"

    def __init__(self) -> None:
        if not settings.forager_api_key:
            raise ValueError("FORAGER_API_KEY is not configured")

        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "X-API-KEY": settings.forager_api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def search_organizations(
        self,
        *,
        domain: str | None = None,
        linkedin_public_identifier: str | None = None,
        organization_ids: list[int] | None = None,
        page: int = 0,
    ) -> dict:
        payload: dict[str, object] = {"page": page}

        if domain:
            payload["domains"] = [domain]

        if linkedin_public_identifier:
            payload["linkedin_public_identifiers"] = [
                linkedin_public_identifier
            ]

        if organization_ids:
            payload["organization_ids"] = organization_ids

        response = await self._client.post(
            f"/api/{settings.forager_account_id}/datastorage/organization_search/",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    
    async def lookup_organizations(
        self,
        query: str,
        page: int = 0,
    ) -> dict:
        response = await self._client.get(
            f"/api/{settings.forager_account_id}/datastorage/organizations/",
            params={"q": query, "page": page},
        )
        response.raise_for_status()
        return response.json()

    
  
   
    async def search_person_roles(
        self,
        *,
        role_title: str,
        organization_domain: str = "openai.com",
        page: int = 0,
    ) -> dict:
        # Search current roles at the company without sending
        # the title query that Forager currently rejects.
        payload = {
            "page": page,
            "role_is_current": True,
            "organization_domains": [organization_domain],
        }

        response = await self._client.post(
            f"/api/{settings.forager_account_id}/datastorage/person_role_search/",
            json=payload,
        )

        if response.is_error:
            import logging

            logging.getLogger(__name__).error(
                "Forager person-role search rejected request: "
                "status=%s, response=%s",
                response.status_code,
                response.text[:1500],
            )

        response.raise_for_status()
        return response.json()



    async def close(self) -> None:
        await self._client.aclose()
