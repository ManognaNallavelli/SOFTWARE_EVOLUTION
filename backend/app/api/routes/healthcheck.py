"""Health check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import get_settings
from app.db.mongo import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Return a structured response confirming the API (and MongoDB) are running."""
    settings = get_settings()
    mongo_ok = False
    try:
        await get_db().command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False

    return HealthResponse(
        status="ok" if mongo_ok else "degraded",
        service=settings.app_name,
        environment=settings.app_env,
        timestamp=datetime.now(timezone.utc),
        mongodb="connected" if mongo_ok else "unavailable",
        google_oauth="configured" if settings.google_oauth_configured else "not_configured",
        gemini="configured" if settings.gemini_api_key.strip() else "not_configured",
    )
