"""Weather endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..cache import cache
from ..config import get_settings
from ..schemas import LocationInfo, WeatherBundle
from ..services import open_meteo, reverse_geo

router = APIRouter(prefix="/api", tags=["weather"])


@router.get("/weather/current", response_model=WeatherBundle)
async def get_current_weather(
    lat: float = Query(..., ge=-90, le=90, description="Latitude of the point"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude of the point"),
    units: str = Query("metric", pattern="^(metric|imperial)$"),
    days: int = Query(7, ge=1, le=16),
) -> WeatherBundle:
    """Current conditions, 24h hourly and 7 day forecast for a coordinate."""
    settings = get_settings()
    key = f"weather:{lat:.2f}:{lon:.2f}:{units}:{days}"

    async def produce() -> WeatherBundle:
        return await open_meteo.fetch_weather(lat, lon, units=units, days=days)

    bundle, stale = await cache.get_or_set(
        key, settings.cache_ttl_weather, produce, stale_on_error=True
    )
    bundle = bundle.model_copy()
    bundle.stale = stale
    return bundle


@router.get("/weather/reverse")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict:
    """Human readable place name for a coordinate (used by the geolocation button)."""
    name = await reverse_geo.reverse_geocode(lat, lon)
    if not name:
        return {"name": None, "latitude": lat, "longitude": lon}
    return {"name": name, "latitude": lat, "longitude": lon}


@router.get("/weather/location")
async def describe_location(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> LocationInfo:
    """Resolve coordinates to a LocationInfo using forward search results."""
    name = await reverse_geo.reverse_geocode(lat, lon)
    return LocationInfo(
        name=name or f"{lat:.3f}, {lon:.3f}",
        latitude=lat,
        longitude=lon,
        source="coordinates",
    )
