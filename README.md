# Forager × HubSpot Automation

## Overview
This project implements an automation layer that connects HubSpot CRM and Forager data to enrich company and contact records for OpenAI-related use cases.

The system is built with Python and FastAPI and exposes webhook endpoints that receive HubSpot events, validate the payloads, and trigger enrichment workflows using Forager data.

## Implemented Work

### 1. Project foundation
- Python project configured with FastAPI, httpx, pydantic-settings, and dev tooling.
- Application entry point created in `app/main.py`.
- Health and root endpoints added for service readiness checks.
- Environment configuration added in `app/config.py` using `.env` values:
  - `FORAGER_API_KEY`
  - `FORAGER_ACCOUNT_ID`
  - `HUBSPOT_ACCESS_TOKEN`

### 2. HubSpot client integration
Implemented in `app/clients/hubspot.py`.

Completed features:
- Initialize async HubSpot API client with bearer token auth.
- List companies from HubSpot CRM.
- Fetch a single company by ID.
- Search companies by domain.
- Create a new HubSpot company.
- Search contacts by LinkedIn URL.
- Create a new contact.
- Associate a contact with a company.
- Get a contact record and associated companies.
- Update contact properties.
- Properly close the HTTP client.

### 3. Forager client integration
Implemented in `app/clients/forager.py`.

Completed features:
- Async Forager API client setup.
- Search organizations by ID, domain, or LinkedIn identifier.
- Search organizations by text query.
- Search person-role records by domain and role.
- Safe HTTP error handling and client cleanup.

### 4. OpenAI company enrichment
Implemented in `app/services/company_enrichment.py`.

Completed features:
- Validate that the Forager record is truly OpenAI.
- Search Forager for the OpenAI organization record.
- Ensure the domain is `openai.com`.
- Check whether the company already exists in HubSpot.
- Create a HubSpot company if it does not exist.
- Return a clean summary payload with status values such as `created` and `already_exists`.

### 5. Contact enrichment workflow
Implemented in `app/services/contact_event_enrichment.py`.

Completed features:
- Fetch the HubSpot contact and associated company.
- Validate that the associated company has a usable domain.
- Search Forager using the company domain and job context.
- Match contacts by:
  - first name
  - last name
  - current role/company domain
  - valid LinkedIn profile URL
- Prevent ambiguous or unsafe updates.
- Fill only missing supported contact fields such as:
  - `hs_linkedin_url`
  - `jobtitle`
  - `city`
  - `state`
  - `country`
- Update HubSpot only when a valid, needed change exists.
- Return status payloads including:
  - `enriched`
  - `already_complete`
  - `not_found`
  - `ambiguous`
  - `skipped`

### 6. HubSpot webhook handling
Implemented in `app/webhooks/router.py`.

Completed features:
- API router mounted under `/webhooks`.
- Event schema validation through Pydantic models.
- Validation of positive numeric object IDs.
- Company creation webhook endpoint: `/webhooks/company-created`.
- Contact creation webhook endpoint: `/webhooks/contact-created`.
- Generic HubSpot event endpoint: `/webhooks/hubspot`.
- Support for legacy and generic event formats.
- Logging and HTTP error handling for upstream failures.
- Response model for structured webhook responses.

### 7. Service orchestration and app wiring
Implemented in `app/main.py` and application package structure.

Completed features:
- FastAPI app defined with service metadata.
- Root endpoint for service status.
- Health endpoint for monitoring.
- Webhook router included in the main app.

### 8. Validation scripts
Included in the repo root:
- `check_forager.py` — verifies the Forager API integration and prints organization details.
- `check_hubspot_client.py` — verifies the HubSpot client can read company data.

These scripts help confirm both APIs are working independently before webhook-based automation is exercised.

## Architecture Summary
The project follows a layered design:

- `app/config.py` — environment configuration and settings.
- `app/clients/forager.py` — Forager API calls.
- `app/clients/hubspot.py` — HubSpot API calls.
- `app/services/company_enrichment.py` — OpenAI company creation logic.
- `app/services/contact_event_enrichment.py` — HubSpot contact enrichment logic.
- `app/webhooks/router.py` — webhook endpoints and event routing.
- `app/main.py` — app bootstrap and router registration.

## Result
The automation currently supports:
- OpenAI company verification and creation in HubSpot.
- Screening Of current OpenAI research-person records from Forager.
- Matching and enriching HubSpot contacts with LinkedIn and location data.
- Automatic association of qualifying contacts to the correct HubSpot company.
- Event-driven processing from HubSpot webhook payloads.

## Notes
The implementation is focused on safe automation:
- Only valid object IDs are processed.
- Unsupported domains are ignored.
- Duplicate or ambiguous matches are not updated.
- Missing fields are updated without overwriting existing values.
- HTTP failures and unexpected issues are logged and surfaced via API responses.
