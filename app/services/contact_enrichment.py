import logging
from typing import Any

import httpx

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient

logger = logging.getLogger(__name__)

OPENAI_DOMAIN = "openai.com"
OPENAI_HUBSPOT_COMPANY_ID = "355353892538"
TARGET_CONTACT_COUNT = 5
MAX_PAGES = 10


def is_candidate(
    item: dict[str, Any],
    job_title_filter: str | None = None,
) -> bool:
    """Validate current OpenAI contacts and optionally filter by job title."""
    organization = item.get("organization") or {}
    person = item.get("person") or {}
    linkedin = person.get("linkedin_info") or {}

    headline = (person.get("headline") or "").strip().lower()
    role_title = (item.get("role_title") or "").strip().lower()
    profile_url = linkedin.get("public_profile_url") or ""
    domain = (organization.get("domain") or "").strip().lower()

    # Required contact validation
    if domain != OPENAI_DOMAIN:
        return False

    if item.get("is_current") is not True:
        return False

    if not person.get("first_name") or not person.get("last_name"):
        return False

    if not profile_url.startswith("https://www.linkedin.com/in/"):
        return False

    if "student" in headline:
        return False

    # Optional job-title filter
    if job_title_filter:
        requested_title = job_title_filter.strip().lower()

        if (
            requested_title not in role_title
            and requested_title not in headline
        ):
            return False

    return True



def extract_location(person: dict[str, Any]) -> dict[str, str]:
    """Extract available city, state and country from Forager locations."""
    location = person.get("location") or {}
    places = location.get("osm_locations") or []
    properties: dict[str, str] = {}

    for place in places:
        name = place.get("name")
        place_type = place.get("place_type")

        if not name:
            continue

        # Use the most specific location name, not the full comma-separated
        # hierarchy, for city/town values.
        if place_type in ("city", "town", "village", "municipality"):
            properties.setdefault("city", name.split(",")[0].strip())

        elif place_type == "state":
            properties.setdefault("state", name.split(",")[0].strip())

        elif place_type == "country":
            properties.setdefault("country", name.strip())

    return properties



def first_available(
    sources: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> str | None:
    """Return the first non-empty scalar value from known field names."""
    for source in sources:
        for key in keys:
            value = source.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(value)

    return None


def extract_contact_properties(
    item: dict[str, Any],
) -> dict[str, str]:
    """Map available person data to HubSpot contact properties."""
    person = item.get("person") or {}
    linkedin = person.get("linkedin_info") or {}

    properties: dict[str, str] = {
        "firstname": str(person["first_name"]).strip(),
        "lastname": str(person["last_name"]).strip(),
        "jobtitle": (
            person.get("headline")
            or item.get("role_title")
            or "Researcher"
        ).strip(),
        "hs_linkedin_url": linkedin["public_profile_url"].rstrip("/"),
    }

    # Field names vary by provider. Only use values actually returned.
    sources = [
        person,
        item,
        person.get("contact_info") or {},
        person.get("contact_details") or {},
        linkedin,
    ]

    email = first_available(
        sources,
        ("email", "work_email", "business_email", "professional_email"),
    )
    phone = first_available(
        sources,
        ("phone", "phone_number", "mobile_phone", "work_phone"),
    )

    if email:
        properties["email"] = email

    if phone:
        properties["phone"] = phone

    properties.update(extract_location(person))
    return properties


async def enrich_openai_contacts(
    job_title_filter: str | None = None,
) -> dict[str, Any]:
    """
    Find up to five current OpenAI research-related contacts.

    Create missing contacts, fill missing properties on existing contacts,
    and associate each contact with the verified OpenAI company.
    """
    forager = ForagerClient()
    hubspot = HubSpotClient()

    summary: dict[str, Any] = {
        "company_id": OPENAI_HUBSPOT_COMPANY_ID,
        "job_title_filter": job_title_filter,
        "candidates_found": 0,
        "created_and_associated": [],
        "updated_and_associated": [],
        "already_complete": [],
        "created_but_association_failed": [],
        "failed": [],
    }

    try:
        company = await hubspot.get_company(OPENAI_HUBSPOT_COMPANY_ID)
        company_properties = company.get("properties") or {}

        if (
            (company_properties.get("domain") or "").strip().lower()
            != OPENAI_DOMAIN
        ):
            raise ValueError(
                "Configured HubSpot company ID does not belong to openai.com."
            )

        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for page in range(MAX_PAGES):
            data = await forager.search_person_roles(
                role_title= job_title_filter or "Researcher",
                organization_domain=OPENAI_DOMAIN,
                page=page,
            )

            for item in data.get("search_results", []):
                if not is_candidate(item,job_title_filter=job_title_filter,
                                    ):
                    continue

                person = item.get("person") or {}
                linkedin = person.get("linkedin_info") or {}
                profile_url = (
                    linkedin.get("public_profile_url") or ""
                ).rstrip("/")
                normalized_url = profile_url.lower()

                if not normalized_url or normalized_url in seen_urls:
                    continue

                seen_urls.add(normalized_url)
                candidates.append(item)

                if len(candidates) >= TARGET_CONTACT_COUNT:
                    break

            if len(candidates) >= TARGET_CONTACT_COUNT:
                break

        summary["candidates_found"] = len(candidates)

        for item in candidates:
            person = item.get("person") or {}
            full_name = (
                person.get("full_name")
                or f"{person.get('first_name', '')} "
                   f"{person.get('last_name', '')}"
            ).strip()

            properties = extract_contact_properties(item)
            profile_url = properties["hs_linkedin_url"]

            try:
                result = await hubspot.search_contacts_by_linkedin(
                    profile_url
                )
                matches = result.get("results", [])

                if matches:
                    contact_id = str(matches[0]["id"])
                    current = await hubspot.get_contact(contact_id)
                    current_properties = current.get("properties") or {}

                    # Only fill missing values; preserve existing CRM data.
                    updates = {
                        key: value
                        for key, value in properties.items()
                        if current_properties.get(key) in (None, "")
                        and value not in (None, "")
                    }

                    if updates:
                        await hubspot.update_contact(contact_id, updates)
                        contact_status = "updated"
                    else:
                        contact_status = "already_complete"

                else:
                    created = await hubspot.create_contact(properties)
                    contact_id = str(created["id"])
                    contact_status = "created"

            except (httpx.HTTPError, KeyError, ValueError) as exc:
                logger.exception("Contact processing failed.")
                summary["failed"].append(
                    {
                        "name": full_name,
                        "stage": "contact",
                        "error": str(exc),
                    }
                )
                continue

            try:
                await hubspot.associate_contact_with_company(
                    contact_id,
                    OPENAI_HUBSPOT_COMPANY_ID,
                )
            except httpx.HTTPError as exc:
                logger.exception("Contact-company association failed.")
                summary["created_but_association_failed"].append(
                    {
                        "name": full_name,
                        "contact_id": contact_id,
                        "error": str(exc),
                    }
                )
                continue

            record = {
                "name": full_name,
                "contact_id": contact_id,
                "email_available": bool(properties.get("email")),
                "phone_available": bool(properties.get("phone")),
                "location_fields_available": [
                    key
                    for key in ("city", "state", "country")
                    if properties.get(key)
                ],
            }

            if contact_status == "created":
                summary["created_and_associated"].append(record)
            elif contact_status == "updated":
                summary["updated_and_associated"].append(record)
            else:
                summary["already_complete"].append(record)

        return summary

    finally:
        await forager.close()
        await hubspot.close()