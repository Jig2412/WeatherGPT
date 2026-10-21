"""Tile proxy for providers whose tiles require an API key.

The OpenWeatherMap raster layers only work with a key in the tile URL. Rather
than shipping the key to the browser we proxy the tiles through this backend,
so the credential never leaves the server.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx
from fastapi import APIRouter, Path, Response

from ..config import get_settings
from ..errors import MissingConfigError, UpstreamError

router = APIRouter(prefix="/api", tags=["tiles"])

# layer id -> OpenWeatherMap tile product
OWM_PRODUCTS = {
    "temperature": "temperature_new",
    "precipitation": "precipitation_new",
    "wind": "wind_new",
    "clouds": "clouds_new",
}

_tile_cache: dict[str, tuple[float, bytes, str]] = {}
TILE_TTL_SECONDS = 600
MAX_TILES = 400


@router.get("/map/tiles/{layer}/{z}/{x}/{y}.png")
async def proxy_tile(
    layer: str = Path(..., description="Layer id"),
    z: int = Path(..., ge=0, le=19),
    x: int = Path(..., ge=0),
    y: int = Path(..., ge=0),
) -> Response:
    settings = get_settings()
    if not settings.has_weather_key:
        raise MissingConfigError(
            "This map layer needs WEATHER_API_KEY. Add it to backend/.env and restart the API.",
            provider="OpenWeatherMap",
        )

    product = OWM_PRODUCTS.get(layer)
    if product is None:
        raise UpstreamError(
            "OpenWeatherMap",
            f"Unknown map layer '{layer}'.",
            status_code=404,
            code="unknown_layer",
        )

    cache_key = f"{layer}/{z}/{x}/{y}"
    now = time.time()
    cached = _tile_cache.get(cache_key)
    if cached and cached[0] > now:
        _, content, content_type = cached
        return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=600"})

    url = f"{settings.weather_tile_base}/{product}/{z}/{x}/{y}.png"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params={"appid": settings.weather_api_key})
    except httpx.HTTPError as exc:
        raise UpstreamError(
            "OpenWeatherMap",
            f"Could not reach the tile server: {exc.__class__.__name__}.",
            code="upstream_unreachable",
        ) from exc

    if response.status_code != 200:
        raise UpstreamError(
            "OpenWeatherMap",
            f"The tile server returned HTTP {response.status_code}.",
            status_code=502,
            code="upstream_http_error",
        )

    content = response.content
    content_type = response.headers.get("content-type", "image/png")

    if len(_tile_cache) >= MAX_TILES:
        oldest = min(_tile_cache.items(), key=lambda kv: kv[1][0])[0]
        _tile_cache.pop(oldest, None)
    _tile_cache[cache_key] = (now + TILE_TTL_SECONDS, content, content_type)

    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=600"})
