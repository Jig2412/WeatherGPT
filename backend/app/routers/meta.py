"""Service metadata endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import get_settings
from ..schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.version,
        providers={
            "open_meteo": {"configured": True, "requires_key": False, "role": "forecast + geocoding"},
            "rainviewer": {"configured": True, "requires_key": False, "role": "radar tiles"},
            "nws_alerts": {"configured": True, "requires_key": False, "role": "official alerts (US only)"},
            "openweathermap": {
                "configured": settings.has_weather_key,
                "requires_key": True,
                "role": "optional raster map layers",
                "env_var": "WEATHER_API_KEY",
            },
            "anthropic": {
                "configured": settings.has_anthropic_key,
                "requires_key": True,
                "role": "AI weather assistant",
                "env_var": "ANTHROPIC_API_KEY",
                "model": settings.anthropic_model,
            },
        },
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
