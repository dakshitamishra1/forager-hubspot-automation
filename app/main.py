
from fastapi import FastAPI

from app.webhooks.router import router as webhook_router

app = FastAPI(
    title="Forager × HubSpot Automation",
    version="0.1.0",
    description="Company and contact enrichment automation.",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "Forager × HubSpot Automation",
        "status": "running",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


app.include_router(webhook_router)
