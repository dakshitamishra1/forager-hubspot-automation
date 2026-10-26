
import logging
import re
from typing import Any

import httpx

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient

logger = logging.getLogger(__name__)


def normalize_name(value: str | None) -> str:
    """Normalize names for case-insensitive matching."""
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def normalize_domain(value: str | None) -> str:
    """Normalize a company domain."""
    return (value or "").strip().lower().rstrip(".")


def extract_location(person: dict[str, Any]) -> dict[str, str]:
    """Extract supported location properties from a Forager person."""
    location = person.get("location") or {}
    places = location.get("osm_locations") or []

    if not isinstance(places, list):
        return {}

    properties: dict[str, str] = {}

    for place in places:
        if not isinstance(place, dict):
            continue

        name = place.get("name")
        place_type = place.get("place_type")

        if not isinstance(name, str) or not name.strip():
            continue

        value = name.split(",", maxsplit=1)[0].strip()
        if not value:
            continue

        if place_type == "city":
            properties.setdefault("city", value)
        elif place_type == "state":
            properties.setdefault("state", value)
        elif place_type == "country":
            properties.setdefault("country", value)

    return properties


def extract_associated_company_id(
    associations: dict[str, Any],
) -> str | None:
    """Extract a valid company ID from HubSpot association results."""
    if not isinstance(associations, dict):
        return None

    results = associations.get("results") or []
    if not isinstance(results, list):
        return None

    for association in results:
        if not isinstance(association, dict):
            continue

        value = association.get("toObjectId")
        if value is None:
            value = association.get("id")

        if value is not None:
            company_id = str(value).strip()
            if company_id.isdigit() and int(company_id) > 0:
                return company_id

    return None


async def _api_call(step: str, awaitable: Any) -> Any:
    """Log which upstream operation failed without logging credentials."""
    try:
        return await awaitable
    except httpx.HTTPStatusError as exc:
        logger.error(
            "%s failed with HTTP status %s",
            step,
            exc.response.status_code,
        )
        raise
    except httpx.RequestError as exc:
        logger.error(
            "%s failed with network error %s",
            step,
            type(exc).__name__,
        )
        raise


async def enrich_contact_event(contact_id: str) -> dict[str, Any]:
    """
    Enrich one HubSpot contact using a matching current Forager role.

    Only missing properties are filled. Ambiguous or missing matches
    never cause a contact update.
    """
    hubspot: HubSpotClient | None = None
    forager: ForagerClient | None = None

    try:
        hubspot = HubSpotClient()
        forager = ForagerClient()

        # 1. Fetch the contact.
        contact = await _api_call(
            "HubSpot get contact",
            hubspot.get_contact(contact_id),
        )
        contact_properties = contact.get("properties") or {}

        first_name = (
            contact_properties.get("firstname") or ""
        ).strip()
        last_name = (
            contact_properties.get("lastname") or ""
        ).strip()
        job_title = (
            contact_properties.get("jobtitle") or ""
        ).strip()

        if not first_name or not last_name:
            return {
                "status": "skipped",
                "contact_id": contact_id,
                "reason": "Contact needs a first name and last name.",
            }

        # 2. Fetch associated companies.
        associations = await _api_call(
            "HubSpot get contact companies",
            hubspot.get_contact_companies(contact_id),
        )

        company_id = extract_associated_company_id(associations)

        if company_id is None:
            logger.warning(
                "No usable company association found for contact %s",
                contact_id,
            )
            return {
                "status": "skipped",
                "contact_id": contact_id,
                "reason": (
                    "No usable company ID was found in the HubSpot "
                    "association response."
                ),
            }

        # 3. Fetch the company and its domain.
        company = await _api_call(
            "HubSpot get company",
            hubspot.get_company(company_id),
        )
        company_properties = company.get("properties") or {}
        domain = normalize_domain(company_properties.get("domain"))

        if not domain:
            return {
                "status": "skipped",
                "contact_id": contact_id,
                "company_id": company_id,
                "reason": "Associated company has no domain.",
            }

        # 4. Search Forager. The fallback is a search term, not a
        # claim that the contact's actual role is Researcher.
        search_response = await _api_call(
            "Forager person-role search",
            forager.search_person_roles(
                role_title=job_title or "Researcher",
                organization_domain=domain,
                page=0,
            ),
        )

        candidates = search_response.get("search_results") or []

        if not isinstance(candidates, list):
            return {
                "status": "error",
                "contact_id": contact_id,
                "reason": "Unexpected Forager search response format.",
            }

        logger.info(
            "Forager returned %s candidates for domain %s",
            len(candidates),
            domain,
        )

        if candidates and isinstance(candidates[0], dict):
            first = candidates[0]
            logger.info(
                "Forager first-result keys: %s",
                sorted(first.keys()),
            )
            person = first.get("person")
            logger.info(
                "Forager first-result person keys: %s",
                sorted(person.keys())
                if isinstance(person, dict)
                else "person is not a dictionary",
            )
        # 5. Match names, company, current role, and LinkedIn URL.
        matches: list[
            tuple[dict[str, Any], dict[str, Any], str]
        ] = []

        for item in candidates:
            if not isinstance(item, dict):
                continue

            person = item.get("person") or {}
            organization = item.get("organization") or {}

            if not isinstance(person, dict):
                continue
            if not isinstance(organization, dict):
                continue
            if item.get("is_current") is not True:
                continue

            if normalize_domain(organization.get("domain")) != domain:
                continue

            if (
                normalize_name(person.get("first_name"))
                != normalize_name(first_name)
                or normalize_name(person.get("last_name"))
                != normalize_name(last_name)
            ):
                continue

            linkedin_info = person.get("linkedin_info") or {}
            if not isinstance(linkedin_info, dict):
                continue

            profile_url = (
                linkedin_info.get("public_profile_url") or ""
            ).strip()

            if (
                not profile_url.startswith(
                    "https://www.linkedin.com/in/"
                )
                or any(char.isspace() for char in profile_url)
            ):
                continue

            matches.append(
                (item, person, profile_url.rstrip("/"))
            )

        if not matches:
            return {
                "status": "not_found",
                "contact_id": contact_id,
                "company_id": company_id,
                "reason": (
                    "No matching current person was found on the "
                    "Forager page searched."
                ),
            }

        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "contact_id": contact_id,
                "company_id": company_id,
                "reason": (
                    "Multiple Forager records matched; no changes "
                    "were made."
                ),
            }

        item, person, profile_url = matches[0]

        # 6. Fill missing properties only.
        updates: dict[str, str] = {}

        if not (contact_properties.get("hs_linkedin_url") or "").strip():
            updates["hs_linkedin_url"] = profile_url

        if not job_title:
            headline = person.get("headline") or item.get("role_title")
            if isinstance(headline, str) and headline.strip():
                updates["jobtitle"] = headline.strip()

        for key, value in extract_location(person).items():
            existing_value = (
                contact_properties.get(key) or ""
            ).strip()
            if not existing_value:
                updates[key] = value

        if not updates:
            return {
                "status": "already_complete",
                "contact_id": contact_id,
                "company_id": company_id,
                "reason": "No supported fields needed updating.",
            }

        # 7. Update the contact.
        await _api_call(
            "HubSpot update contact",
            hubspot.update_contact(contact_id, updates),
        )

        logger.info(
            "Contact %s enriched; updated fields: %s",
            contact_id,
            ", ".join(sorted(updates)),
        )

        return {
            "status": "enriched",
            "contact_id": contact_id,
            "company_id": company_id,
            "updated_fields": sorted(updates),
        }

    finally:
        # Attempt cleanup of both clients independently.
        for client in (forager, hubspot):
            if client is None:
                continue

            try:
                await client.close()
            except Exception:
                logger.exception(
                    "Failed to close %s",
                    type(client).__name__,
                )
