
from typing import Any
import logging

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient

logger = logging.getLogger(__name__)

FORAGER_OPENAI_ID = 12988797
OPENAI_DOMAIN = "openai.com"


async def enrich_openai_company(company_id: str) -> dict[str, Any]:
    """
    Enrich an existing HubSpot OpenAI company using verified Forager data.
    Only fills properties that are currently missing.
    """
    forager = ForagerClient()
    hubspot = HubSpotClient()

    try:
        # 1. Fetch the existing HubSpot company.
        company = await hubspot.get_company(company_id)
        company_properties = company.get("properties") or {}

        domain = (
            company_properties.get("domain") or ""
        ).strip().lower()

        if domain != OPENAI_DOMAIN:
            return {
                "status": "skipped",
                "company_id": company_id,
                "reason": "Company domain is not openai.com.",
                "updated_fields": [],
            }

        # 2. Fetch OpenAI's organization record from Forager.
        source = await forager.search_organizations(
            organization_ids=[FORAGER_OPENAI_ID],
            page=0,
        )

        organizations = source.get("search_results", [])

        if len(organizations) != 1:
            raise ValueError(
                "Expected exactly one OpenAI organization from Forager."
            )

        organization = organizations[0]

        if (
            organization.get("id") != FORAGER_OPENAI_ID
            or organization.get("name") != "OpenAI"
            or (organization.get("domain") or "").lower()
            != OPENAI_DOMAIN
        ):
            raise ValueError("OpenAI organization verification failed.")

        # 3. Map available organization fields.
        updates: dict[str, str] = {}

        field_mapping = {
            "name": organization.get("name"),
            "domain": organization.get("domain"),
            "description": organization.get("description"),
            "numberofemployees": organization.get("employees_amount"),
        }

        for property_name, value in field_mapping.items():
            current_value = company_properties.get(property_name)

            # Preserve existing HubSpot values.
            if current_value not in (None, ""):
                continue

            if value is None or value == "":
                continue

            updates[property_name] = str(value).strip()

        # # 4. Map revenue if Forager provides a valid numeric value.
        # revenue = organization.get("revenue")
        # print("DEBUG - Forager organization keys:", list(organization.keys()))
        # print("DEBUG - Forager revenue:", repr(revenue), type(revenue).__name__)
        # print("DEBUG - HubSpot annualrevenue:", repr(company_properties.get("annualrevenue")))
        # annual_revenue = None

        finance_info = organization.get("finance_info") or {}

        revenue = organization.get("revenue")

        if revenue is None:
            revenue = finance_info.get("revenue")

     
        if isinstance(revenue, (int, float)) and not isinstance(revenue, bool):
            annual_revenue = revenue
        elif isinstance(revenue, str) and revenue.strip():
            try:
                annual_revenue = float(revenue.strip().replace(",", ""))
            except ValueError:
                logger.warning(
                    "Forager returned an unrecognized revenue value: %r",
                    revenue,
                )

        current_revenue = company_properties.get("annualrevenue")

        if (
            current_revenue in (None, "")
            and annual_revenue is not None
            and annual_revenue >= 0
        ):
            # Send a numeric string to HubSpot.
            if annual_revenue.is_integer() if isinstance(annual_revenue, float) else True:
                updates["annualrevenue"] = str(int(annual_revenue))
            else:
                updates["annualrevenue"] = str(annual_revenue)

        logger.info(
            "Company %s enrichment fields selected: %s",
            company_id,
            sorted(updates),
        )

        # 5. Return if there is genuinely nothing to update.
        if not updates:
            return {
                "status": "already_complete",
                "company_id": company_id,
                "updated_fields": [],
                "reason": (
                    "No missing supported properties had usable source values."
                ),
            }

        # 6. Update the same HubSpot company record.
        updated = await hubspot.update_company(company_id, updates)

        return {
            "status": "enriched",
            "company_id": company_id,
            "updated_fields": sorted(updates),
            "properties": updated.get("properties", {}),
        }

    finally:
        await forager.close()
        await hubspot.close()
