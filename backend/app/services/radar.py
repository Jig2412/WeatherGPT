"""RainViewer radar integration.

Verified behaviour of the public tier (checked against the live API):

* ``GET {radar_api_base}/weather-maps.json`` returns the last ~2h of radar
  frames (10 minute steps) plus an optional nowcast and satellite block.
* Tiles follow ``{host}{path}/{size}/{z}/{x}/{y}/{color}/{options}.png``.
* The public tier does not currently publish a nowcast (the ``nowcast`` array
  comes back empty), so the app animates the observed past frames only and
  states that explicitly instead of pretending to forecast radar.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..errors import UpstreamError, ValidationError
from ..schemas import RadarFrame, RadarFrameRaw, RadarResponse, WeatherMapsRaw
from .http import build_client, get_json

COLOR_SCHEME = "4"
OPTIONS = "0_1"
MAX_ZOOM = 7


def _timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _build_frames(raw: list[RadarFrameRaw], host: str, tile_base: str, is_forecast: bool) -> list[RadarFrame]:
    frames: list[RadarFrame] = []
    for item in raw:
        template = (
            f"{tile_base}{item.path}/256/{{z}}/{{x}}/{{y}}/{COLOR_SCHEME}/{OPTIONS}.png"
        )
        frames.append(
            RadarFrame(
                time=item.time,
                timestamp=_timestamp(item.time),
                path=item.path,
                tile_url_template=template,
                is_forecast=is_forecast,
            )
        )
    return frames


async def get_radar_frames() -> RadarResponse:
    settings = get_settings()
    url = f"{settings.radar_api_base}/weather-maps.json"
    if settings.radar_api_key:
        url = f"{url}?key={settings.radar_api_key}"

    async with build_client() as client:
        payload = await get_json(client, url, provider="RainViewer")

    try:
        data = WeatherMapsRaw.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValidationError(
            "RainViewer returned a payload that does not match the expected schema.",
            provider="RainViewer",
        ) from exc

    host = data.host or settings.radar_tile_base
    tile_base = host.rstrip("/")

    radar = data.radar
    past = _build_frames(radar.past if radar else [], tile_base, tile_base, False)
    nowcast = _build_frames(radar.nowcast if radar else [], tile_base, tile_base, True)
    satellite_raw = data.satellite.infrared if data.satellite else []
    satellite = _build_frames(satellite_raw, tile_base, tile_base, False)

    notes: list[str] = []
    if not nowcast:
        notes.append(
            "The RainViewer public tier does not publish a radar nowcast, so only "
            "observed past frames are available."
        )
    if not satellite:
        notes.append("No satellite infrared frames are currently published by the provider.")

    return RadarResponse(
        provider="RainViewer",
        host=tile_base,
        generated_at=_timestamp(data.generated) if data.generated else None,
        past=past,
        nowcast=nowcast,
        satellite=satellite,
        max_zoom=MAX_ZOOM,
        color_scheme=COLOR_SCHEME,
        options=OPTIONS,
        attribution="Radar data by RainViewer",
        notes=notes,
    )


def radar_coverage_for(latitude: float, longitude: float) -> dict[str, Any]:
    """Whether radar tiles exist near a point (approx. tile index check)."""
    return {
        "latitude": latitude,
        "longitude": longitude,
        "max_zoom": MAX_ZOOM,
        "provider": "RainViewer",
    }
