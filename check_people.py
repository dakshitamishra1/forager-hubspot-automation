
import asyncio

from app.clients.forager import ForagerClient


async def main():
    client = ForagerClient()

    try:
        found = 0
        seen_linkedin_urls = set()
        target_count = 5

        for page in range(10):
            data = await client.search_person_roles(
                role_title="Researcher",
                organization_domain="openai.com",
                page=page,
            )

            records = data.get("search_results", [])
            print(f"Page {page}: {len(records)} records")

            for item in records:
                organization = item.get("organization") or {}
                person = item.get("person") or {}
                linkedin = person.get("linkedin_info") or {}
                location = person.get("location") or {}

                profile_url = linkedin.get("public_profile_url")
                headline = (person.get("headline") or "").strip()
                headline_lower = headline.lower()

                # Require a current role at the correct company.
                if organization.get("domain") != "openai.com":
                    continue

                if item.get("is_current") is not True:
                    continue

                first_name = person.get("first_name")
                last_name = person.get("last_name")

                if not first_name or not last_name or not profile_url:
                    continue

                # Exclude obvious headline mismatches.
                credible_headline = (
                    "openai" in headline_lower
                    or "researcher" in headline_lower
                    or "research" in headline_lower
                )

                if not credible_headline:
                    continue

                if "student" in headline_lower:
                    continue

                # Avoid duplicate profiles in the search results.
                normalized_url = profile_url.rstrip("/").lower()

                if normalized_url in seen_linkedin_urls:
                    continue

                seen_linkedin_urls.add(normalized_url)

                print({
                       "first_name": person.get("first_name"),
                       "last_name": person.get("last_name"),
                       "role": item.get("role_title"),
                       "headline": person.get("headline"),
                       "linkedin_url": profile_url,
                       "location": (person.get("location") or {}).get("name"),
                       "person_fields": list(person.keys()),
                       "linkedin_fields": list(linkedin.keys()),
                       "contact_info": person.get("contact_info"),
                       "contact_details": person.get("contact_details"),
                       "location_data": person.get("location"),
})

                found += 1

                if found >= target_count:
                    break

            if found >= target_count:
                break

        print(f"\nCandidate profiles found: {found}")

        if found < target_count:
            print(
                f"Only {found} candidates passed the filters. "
                "Review the filters or inspect additional results."
            )

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
