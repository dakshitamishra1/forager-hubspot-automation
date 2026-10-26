
import asyncio

from app.services.company_enrichment import enrich_openai_company


async def main() -> None:
    result = await enrich_openai_company()
    print("Company enrichment result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
