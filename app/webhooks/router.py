
import logging
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.clients.hubspot import HubSpotClient
from app.services.company_enrichment import enrich_openai_company
from app.services.contact_enrichment import enrich_openai_contacts
from app.services.contact_event_enrichment import enrich_contact_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["HubSpot webhooks"])


class HubSpotEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subscription_type: str = Field(alias="subscriptionType", min_length=1)
    object_id: int | str = Field(alias="objectId")
    object_type_id: str | None = Field(default=None, alias="objectTypeId")
    event_id: int | str | None = Field(default=None, alias="eventId")
    attempt_number: int | None = Field(default=None, alias="attemptNumber")


class WebhookResponse(BaseModel):
    status: str
    event_type: str
    object_id: str
    detail: str


def validate_object_id(value: int | str) -> str:
    """Accept only positive numeric HubSpot object IDs."""
    object_id = str(value).strip()

    if not object_id.isdigit() or int(object_id) <= 0:
        raise HTTPException(status_code=400, detail="Invalid HubSpot object ID.")

    return object_id


@router.post("/company-created", response_model=list[WebhookResponse])
async def company_created(
    events: list[HubSpotEvent],
) -> list[WebhookResponse]:
    if not events:
        raise HTTPException(status_code=400, detail="Event list cannot be empty.")

    responses: list[WebhookResponse] = []

    for event in events:
        if event.subscription_type != "company.creation":
            responses.append(
                WebhookResponse(
                    status="ignored",
                    event_type=event.subscription_type,
                    object_id=str(event.object_id),
                    detail="Event type is not handled by this endpoint.",
                )
            )
            continue

        company_id = validate_object_id(event.object_id)
        hubspot = HubSpotClient()

        try:
            company = await hubspot.get_company(company_id)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpot company retrieval failed: status=%s",
                exc.response.status_code,
            )
            raise HTTPException(
                status_code=502,
                detail="Could not retrieve the company from HubSpot.",
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "HubSpot company retrieval network error: %s",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail="Could not connect to HubSpot.",
            ) from exc
        finally:
            await hubspot.close()

        properties = company.get("properties") or {}
        domain = (properties.get("domain") or "").strip().lower()

        # The existing company service is specifically for OpenAI.
        if domain != "openai.com":
            responses.append(
                WebhookResponse(
                    status="skipped",
                    event_type=event.subscription_type,
                    object_id=company_id,
                    detail=(
                        "Company enrichment currently supports "
                        "the OpenAI domain only."
                    ),
                )
            )
            continue

        try:
            result = await enrich_openai_company(company_id)
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("OpenAI company enrichment failed.")
            raise HTTPException(
                status_code=502,
                detail="Company enrichment failed. Check server logs.",
            ) from exc

        # Discover contacts only for the configured OpenAI demo company.
        contacts_detail = "Contact discovery not run."
        if company_id == "355353892538":
            try:
                contacts_result = await enrich_openai_contacts()
                contacts_detail = (
                    "Contact discovery found "
                    f"{contacts_result.get('candidates_found', 0)} candidates."
                )
            except Exception:
                logger.exception("OpenAI contact discovery failed.")
                contacts_detail = (
                    "Contact discovery failed; check server logs."
                )

        responses.append(
            WebhookResponse(
                status=result.get("status", "processed"),
                event_type=event.subscription_type,
                object_id=company_id,
                detail=(
                    "OpenAI company enrichment result: "
                    f"{result.get('status', 'completed')}. {contacts_detail}"
                ),
            )
        )

    return responses


@router.post("/contact-created", response_model=list[WebhookResponse])
async def contact_created(
    events: list[HubSpotEvent],
) -> list[WebhookResponse]:
    if not events:
        raise HTTPException(
            status_code=400,
            detail="Event list cannot be empty.",
        )

    responses: list[WebhookResponse] = []

    for event in events:
        if event.subscription_type != "contact.creation":
            responses.append(
                WebhookResponse(
                    status="ignored",
                    event_type=event.subscription_type,
                    object_id=str(event.object_id),
                    detail="Event type is not handled by this endpoint.",
                )
            )
            continue

        contact_id = validate_object_id(event.object_id)

        try:
            result = await enrich_contact_event(contact_id)

        except httpx.HTTPStatusError as exc:
            logger.exception(
                "Contact enrichment upstream HTTP failure: status=%s",
                exc.response.status_code,
            )
            raise HTTPException(
                status_code=502,
                detail="An upstream API returned an HTTP error. "
                "Check server logs.",
            ) from exc

        except httpx.RequestError as exc:
            logger.exception(
                "Contact enrichment network failure: %s",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail="Could not connect to an upstream API. "
                "Check server logs.",
            ) from exc

        except ValueError as exc:
            logger.exception("Contact enrichment validation error.")
            raise HTTPException(
                status_code=502,
                detail="Contact enrichment validation failed. "
                "Check server logs.",
            ) from exc

        except Exception as exc:
            logger.exception(
                "Unexpected contact enrichment failure: %s",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="Unexpected contact enrichment failure. "
                "Check server logs.",
            ) from exc

        status = result.get("status", "unknown")
        detail = result.get("reason") or (
            f"Contact enrichment result: {status}"
        )

        responses.append(
            WebhookResponse(
                status=status,
                event_type=event.subscription_type,
                object_id=contact_id,
                detail=detail,
            )
        )

    return responses


@router.post("/hubspot", response_model=list[WebhookResponse])
async def hubspot_webhook(
    events: list[HubSpotEvent],
) -> list[WebhookResponse]:
    if not events:
        raise HTTPException(
            status_code=400,
            detail="Event list cannot be empty.",
        )

    responses: list[WebhookResponse] = []

    for event in events:
        event_type = event.subscription_type

        # Support the legacy event names and the generic event format.
        if event_type == "contact.creation" or (
            event_type == "object.creation"
            and event.object_type_id == "0-1"
        ):
            contact_id = validate_object_id(event.object_id)

            try:
                result = await enrich_contact_event(contact_id)
            except httpx.HTTPError as exc:
                logger.exception("Contact enrichment HTTP failure.")
                raise HTTPException(
                    status_code=502,
                    detail="Contact enrichment failed. Check server logs.",
                ) from exc
            except ValueError as exc:
                logger.exception("Contact enrichment validation failure.")
                raise HTTPException(
                    status_code=502,
                    detail="Contact enrichment validation failed.",
                ) from exc

            status = result.get("status", "unknown")
            responses.append(
                WebhookResponse(
                    status=status,
                    event_type=event_type,
                    object_id=contact_id,
                    detail=result.get("reason")
                    or f"Contact enrichment result: {status}",
                )
            )

        elif event_type == "company.creation" or (
            event_type == "object.creation"
            and event.object_type_id == "0-2"
        ):
            company_id = validate_object_id(event.object_id)
            hubspot = HubSpotClient()

            try:
                company = await hubspot.get_company(company_id)
            except httpx.HTTPError as exc:
                logger.exception("HubSpot company retrieval failed.")
                raise HTTPException(
                    status_code=502,
                    detail="Could not retrieve company from HubSpot.",
                ) from exc
            finally:
                await hubspot.close()

            domain = (
                (company.get("properties") or {}).get("domain") or ""
            ).strip().lower()

            if domain != "openai.com":
                responses.append(
                    WebhookResponse(
                        status="skipped",
                        event_type=event_type,
                        object_id=company_id,
                        detail=(
                            "Company enrichment currently supports "
                            "the OpenAI domain only."
                        ),
                    )
                )
                continue

            try:
                result = await enrich_openai_company(company_id)
            except (httpx.HTTPError, ValueError) as exc:
                logger.exception("Company enrichment failed.")
                raise HTTPException(
                    status_code=502,
                    detail="Company enrichment failed. Check server logs.",
                ) from exc

            status = result.get("status", "processed")

            # Run contact discovery for the configured OpenAI demo company.
            contacts_detail = "Contact discovery not run."
            if company_id == "355353892538":
                try:
                    contacts_result = await enrich_openai_contacts()
                    contacts_detail = (
                        "Contact discovery found "
                        f"{contacts_result.get('candidates_found', 0)} candidates."
                    )
                except Exception:
                    logger.exception("OpenAI contact discovery failed.")
                    contacts_detail = (
                        "Contact discovery failed; check server logs."
                    )

            responses.append(
                WebhookResponse(
                    status=status,
                    event_type=event_type,
                    object_id=company_id,
                    detail=(
                        f"Company enrichment result: {status}. "
                        f"{contacts_detail}"
                    ),
                )
            )

        else:
            responses.append(
                WebhookResponse(
                    status="ignored",
                    event_type=event_type,
                    object_id=str(event.object_id),
                    detail=(
                        "Event type or object type is not handled "
                        "by this endpoint."
                    ),
                )
            )

    return responses
