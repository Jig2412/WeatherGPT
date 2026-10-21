"""Official weather alert endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..cache import cache
from ..config import get_settings
from ..schemas import AlertsResponse
from ..services import alerts

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> AlertsResponse:
    """Official watches, warnings and advisories for a coordinate.

    Returns ``supported: false`` with an explanation when the location is
    outside the coverage of the configured official alert feed.
    """
    settings = get_settings()
    key = f"alerts:{lat:.2f}:{lon:.2f}"

    async def produce() -> AlertsResponse:
        return await alerts.get_alerts(lat, lon)

    response, stale = await cache.get_or_set(key, settings.cache_ttl_alerts, produce)
    response = response.model_copy()
    response.stale = stale
    return response
