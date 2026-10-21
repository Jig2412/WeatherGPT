"""Radar and map-layer endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ..cache import cache
from ..config import get_settings
from ..schemas import MapLayerConfig, MapLayersResponse, RadarResponse
from ..services import radar

router = APIRouter(prefix="/api", tags=["radar"])

# Reflectivity ramp used for the on-map legend. RainViewer publishes the
# "Universal Blue" scheme; the dBZ bands below are the standard reflectivity
# thresholds used to describe radar intensity.
RADAR_LEGEND = [
    {"label": "Light", "dbz": "0-20", "color": "#7cd4fb"},
    {"label": "Moderate", "dbz": "20-35", "color": "#0091ca"},
    {"label": "Heavy", "dbz": "35-45", "color": "#2f9e44"},
    {"label": "Very heavy", "dbz": "45-55", "color": "#f2c744"},
    {"label": "Extreme", "dbz": "55+", "color": "#e03131"},
]

OWM_LAYERS = [
    ("temperature", "Temperature", "temperature_new"),
    ("precipitation", "Precipitation", "precipitation_new"),
    ("wind", "Wind", "wind_new"),
    ("clouds", "Clouds", "clouds_new"),
]

# Indicative colour scales for the OpenWeatherMap raster layers. The provider
# does not publish the exact colour table for these products, so the legend is
# labelled as indicative in the UI.
OWM_LEGENDS: dict[str, list[dict[str, str]]] = {
    "temperature": [
        {"label": "−40°C", "dbz": "-40", "color": "#0d0887"},
        {"label": "−20°C", "dbz": "-20", "color": "#7e03a8"},
        {"label": "0°C", "dbz": "0", "color": "#cc4778"},
        {"label": "20°C", "dbz": "20", "color": "#f89540"},
        {"label": "40°C", "dbz": "40", "color": "#f0f921"},
    ],
    "precipitation": [
        {"label": "0.1 mm/h", "dbz": "0.1", "color": "#a5f3fc"},
        {"label": "1 mm/h", "dbz": "1", "color": "#38bdf8"},
        {"label": "4 mm/h", "dbz": "4", "color": "#22d3ee"},
        {"label": "10 mm/h", "dbz": "10", "color": "#4ade80"},
        {"label": "25 mm/h", "dbz": "25", "color": "#facc15"},
        {"label": "50 mm/h", "dbz": "50", "color": "#ef4444"},
    ],
    "wind": [
        {"label": "0–3 m/s", "dbz": "3", "color": "#dbeafe"},
        {"label": "3–6 m/s", "dbz": "6", "color": "#93c5fd"},
        {"label": "6–10 m/s", "dbz": "10", "color": "#67e8f9"},
        {"label": "10–15 m/s", "dbz": "15", "color": "#86efac"},
        {"label": "15–20 m/s", "dbz": "20", "color": "#fde047"},
        {"label": "20+ m/s", "dbz": "20+", "color": "#f87171"},
    ],
    "clouds": [
        {"label": "0–20%", "dbz": "20", "color": "#1e293b"},
        {"label": "20–40%", "dbz": "40", "color": "#334155"},
        {"label": "40–60%", "dbz": "60", "color": "#64748b"},
        {"label": "60–80%", "dbz": "80", "color": "#94a3b8"},
        {"label": "80–100%", "dbz": "100", "color": "#e2e8f0"},
    ],
}


@router.get("/radar/frames", response_model=RadarResponse)
async def radar_frames() -> RadarResponse:
    """Observed radar frames published by RainViewer."""
    settings = get_settings()
    key = "radar:frames"

    async def produce() -> RadarResponse:
        return await radar.get_radar_frames()

    response, stale = await cache.get_or_set(key, settings.cache_ttl_radar, produce)
    response = response.model_copy()
    if stale:
        response.notes = list(response.notes) + ["Serving a cached copy: the provider is unreachable right now."]
    return response


@router.get("/map/layers", response_model=MapLayersResponse)
async def map_layers() -> MapLayersResponse:
    """Which real weather layers the map can currently render.

    Layers that need a provider key are reported as unavailable instead of
    silently substituting decorative overlays.
    """
    settings = get_settings()
    layers: list[MapLayerConfig] = []

    layers.append(
        MapLayerConfig(
            id="radar",
            label="Radar (RainViewer)",
            kind="raster",
            available=True,
            provider="RainViewer",
            url_template="{host}{path}/256/{z}/{x}/{y}/4/0_1.png",
            opacity_default=0.8,
            requires_api_key=False,
            legend=RADAR_LEGEND,
        )
    )

    for layer_id, label, owm_name in OWM_LAYERS:
        available = settings.has_weather_key
        layers.append(
            MapLayerConfig(
                id=layer_id,
                label=label,
                kind="raster" if available else "none",
                available=available,
                provider="OpenWeatherMap",
                # Tiles are proxied by the backend so the API key is never
                # exposed to the browser.
                url_template=(
                    f"/api/map/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png" if available else None
                ),
                opacity_default=0.6,
                requires_api_key=True,
                config_var="WEATHER_API_KEY" if not available else None,
                legend=OWM_LEGENDS.get(layer_id) if available else None,
                unavailable_reason=(
                    None
                    if available
                    else "Set WEATHER_API_KEY in backend/.env to enable the OpenWeatherMap raster layers."
                ),
            )
        )

    return MapLayersResponse(
        layers=layers,
        attribution=[
            "Radar data by RainViewer",
            "Weather data by Open-Meteo.com",
            "Base map © OpenStreetMap contributors",
        ],
    )
