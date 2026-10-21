"""Reverse geocoding used to label the browser's current position.

Uses the keyless BigDataCloud client endpoint. This is only used for a human
readable place name -- all weather values still come from Open-Meteo using the
raw coordinates.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import get_settings
from ..errors import UpstreamError
from .http import build_client, get_json


async def reverse_geocode(latitude: float, longitude: float) -> Optional[str]:
    settings = get_settings()
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "localityLanguage": "en",
    }
    try:
        async with build_client() as client:
            payload = await get_json(
                client,
                settings.reverse_geo_url,
                provider="BigDataCloud Reverse Geocoding",
                params=params,
            )
    except UpstreamError:
        return None

    if not isinstance(payload, dict):
        return None

    city = payload.get("city") or payload.get("locality") or payload.get("principalSubdivision")
    if not city:
        return None

    country = payload.get("countryName")
    return f"{city}, {country}" if country else str(city)
