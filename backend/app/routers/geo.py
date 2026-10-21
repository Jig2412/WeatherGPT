"""Location search endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..cache import cache
from ..config import get_settings
from ..schemas import GeocodeResult
from ..services import geocoding

router = APIRouter(prefix="/api", tags=["geocoding"])


@router.get("/geocode", response_model=GeocodeResult)
async def search(
    q: str = Query(..., min_length=2, max_length=120, description="Place name"),
    count: int = Query(8, ge=1, le=20),
    language: str = Query("en", max_length=8),
) -> GeocodeResult:
    """Autocomplete-style place search backed by the Open-Meteo geocoding API."""
    settings = get_settings()
    key = f"geocode:{q.lower().strip()}:{count}:{language}"

    async def produce() -> list:
        return await geocoding.search_locations(q, count=count, language=language)

    results, _ = await cache.get_or_set(key, settings.cache_ttl_geocode, produce)
    return GeocodeResult(results=results, query=q)
