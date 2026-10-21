"""Open-Meteo geocoding client (forward search)."""
from __future__ import annotations

from typing import Optional

from ..config import get_settings
from ..errors import UpstreamError, ValidationError
from ..schemas import GeoResponse, LocationInfo
from .http import build_client, get_json


async def search_locations(
    query: str, *, count: int = 8, language: str = "en"
) -> list[LocationInfo]:
    """Search for places by name. Returns an empty list when nothing matches."""
    query = (query or "").strip()
    if len(query) < 2:
        return []

    settings = get_settings()
    params = {
        "name": query,
        "count": max(1, min(count, 20)),
        "language": language,
        "format": "json",
    }

    async with build_client() as client:
        payload = await get_json(
            client,
            f"{settings.geocoding_base}/search",
            provider="Open-Meteo Geocoding",
            params=params,
        )

    try:
        data = GeoResponse.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValidationError(
            "Geocoding response did not match the expected schema.",
            provider="Open-Meteo Geocoding",
        ) from exc

    locations: list[LocationInfo] = []
    for item in data.results:
        locations.append(
            LocationInfo(
                name=item.name,
                latitude=item.latitude,
                longitude=item.longitude,
                country=item.country,
                country_code=item.country_code,
                admin1=item.admin1,
                timezone=item.timezone,
                elevation=item.elevation,
                population=item.population,
                source="geocoding",
            )
        )
    return locations


async def resolve_location(query: str) -> Optional[LocationInfo]:
    """Best-effort single match used by the AI assistant tools."""
    results = await search_locations(query, count=1)
    return results[0] if results else None
