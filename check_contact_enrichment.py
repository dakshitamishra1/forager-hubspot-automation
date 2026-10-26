
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient

logger = logging.getLogger(__name__)


def normalize_name(value: str | None) -> str:
    """Normalize names for case-insensitive matching."""
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def normalize_domain(value: str | None) -> str:
    """Normalize a domain for comparison."""
    return (value or "").strip().lower().rstrip(".")


def extract_location(person: dict[str, Any]) -> dict[str, str]:
    """Extract supported location fields from a Forager person."""
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
    """
    Extract a company ID from a HubSpot association response.

    CRM v4 responses commonly use `toObjectId`. The `id` fallback
    accommodates alternate response formats. No ID is fabricated.
    """
    if not isinstance(associations, dict):
        return None

    results = associations.get("results") or []
    if not isinstance(results, list):
        return None

    for association in results:
        if not isinstance(association, dict):
            continue

        company_id = association.get("toObjectId")
        if company_id is None:
            company_id = association.get("id")

        if company_id is not None:
            value = str(company_id).strip()
            if value.isdigit() and int(value) > 0:
                return value

    return None


def is_linkedin_profile_url(value: str) -> bool:
    """Accept only HTTPS LinkedIn personal-profile URLs."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    hostname = (parsed.hostname or "").lower()

    return (
        parsed.scheme == "https"
        and hostname == "www.linkedin.com"
        and parsed.path.startswith("/in/")
        and len(parsed.path.strip("/").split("/")) >= 2
        and not parsed.username
        and not parsed.password
    )


async def enrich_contact_event(contact_id: str) -> dict[str, Any]:
    """
    Enrich one HubSpot contact using a conservative Forager match.

    Only missing supported properties are updated. If there is no safe,
    unique match, the contact is left unchanged.
    """
    hubspot: HubSpotClient | None = None
    forager: ForagerClient | None = None

    try:
        hubspot = HubSpotClient()
        forager = ForagerClient()

        # 1. Retrieve the HubSpot contact.
        contact = await hubspot.get_contact(contact_id)
        contact_properties = contact.get("properties") or {}

        first_name = (
            contact_properties.get("firstname") or ""
        ).strip()
        last_name = (
            contact_properties.get("lastname") or ""
        ).strip()
        existing_job_title = (
            contact_properties.get("jobtitle") or ""
        ).strip()

        if not first_name or not last_name:
            return {
                "status": "skipped",
                "contact_id": contact_id,
                "reason": (
                    "Both first name and last name are required "
                    "for safe matching."
                ),
            }

        # 2. Retrieve associated companies.
        associations = await hubspot.get_contact_companies(contact_id)
        company_id = extract_associated_company_id(associations)

        if company_id is None:
            logger.info(
                "No usable company association for contact %s",
                contact_id,
            )
            return {
                "status": "skipped",
                "contact_id": contact_id,
                "reason": (
                    "No usable associated company ID was found "
                    "in the HubSpot response."
                ),
            }

        # 3. Retrieve the company domain.
        company = await hubspot.get_company(company_id)
        company_properties = company.get("properties") or {}
        domain = normalize_domain(company_properties.get("domain"))

        if not domain:
            return {
                "status": "skipped",
                "contact_id": contact_id,
                "company_id": company_id,
                "reason": "Associated company has no domain.",
            }

        # 4. Search Forager for current roles at this company.
        search_title = existing_job_title or "Researcher"

        search_response = await forager.search_person_roles(
            role_title=search_title,
            organization_domain=domain,
            page=0,
        )

        candidates = search_response.get("search_results") or []

        if not isinstance(candidates, list):
            logger.warning(
                "Unexpected Forager search response for contact %s",
                contact_id,
            )
            return {
                "status": "error",
                "contact_id": contact_id,
                "reason": "Unexpected Forager search response format.",
            }

        # 5. Require matching names, company domain, current role,
        # and a valid personal LinkedIn URL.
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

            candidate_domain = normalize_domain(
                organization.get("domain")
            )
            if candidate_domain != domain:
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

            if not is_linkedin_profile_url(profile_url):
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
                    "No matching current person was found on "
                    "the Forager page searched."
                ),
            }

        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "contact_id": contact_id,
                "company_id": company_id,
                "reason": (
                    "Multiple Forager records matched. "
                    "No contact fields were changed."
                ),
            }

        item, person, profile_url = matches[0]

        # 6. Fill missing properties only.
        updates: dict[str, str] = {}

        existing_linkedin = (
            contact_properties.get("hs_linkedin_url") or ""
        ).strip()

        if not existing_linkedin:
            updates["hs_linkedin_url"] = profile_url

        if not existing_job_title:
            headline = (
                person.get("headline")
                or item.get("role_title")
                or ""
            )
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
                "reason": (
                    "All supported enrichment fields are already populated."
                ),
            }

        # 7. Update the HubSpot contact.
        await hubspot.update_contact(contact_id, updates)

        logger.info(
            "Enriched contact %s; updated fields: %s",
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
        # Attempt to close both clients even if one close operation fails.
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
