"""Pydantic schemas.

Two families live here:

* ``O*`` models validate the raw upstream payloads (Open-Meteo, RainViewer, NWS).
  Every optional upstream field is modelled as ``Optional[...]`` because
  Open-Meteo legitimately returns ``null`` for unavailable data.
* The remaining models are the stable API contract consumed by the frontend.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class LocationInfo(BaseModel):
    name: str
    latitude: float
    longitude: float
    country: Optional[str] = None
    country_code: Optional[str] = None
    admin1: Optional[str] = None
    timezone: Optional[str] = None
    elevation: Optional[float] = None
    population: Optional[int] = None
    source: str = "search"

    @property
    def label(self) -> str:
        bits = [self.name]
        if self.admin1 and self.admin1 != self.name:
            bits.append(self.admin1)
        if self.country:
            bits.append(self.country)
        return ", ".join(bits)


class Units(BaseModel):
    temperature: str = "°C"
    wind_speed: str = "km/h"
    precipitation: str = "mm"
    visibility: str = "m"
    pressure: str = "hPa"
    humidity: str = "%"
    cloud_cover: str = "%"
    uv_index: str = ""
    time: str = "iso8601"


class ProviderInfo(BaseModel):
    """Where a number came from and how fresh it is."""

    name: str
    source: str
    data_kind: str = "model"
    model: Optional[str] = None
    retrieved_at: str
    generated_at: Optional[str] = None
    observation_time: Optional[str] = None
    is_model_based: bool = True
    is_live_observation: bool = False
    note: Optional[str] = None
    attribution: Optional[str] = None


class CurrentWeather(BaseModel):
    observed_at: Optional[str] = None
    temperature: Optional[float] = None
    feels_like: Optional[float] = None
    humidity: Optional[float] = None
    precipitation: Optional[float] = None
    rain: Optional[float] = None
    showers: Optional[float] = None
    snowfall: Optional[float] = None
    weather_code: Optional[int] = None
    weather_label: Optional[str] = None
    cloud_cover: Optional[int] = None
    pressure_msl: Optional[float] = None
    surface_pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[int] = None
    wind_gusts: Optional[float] = None
    uv_index: Optional[float] = None
    visibility: Optional[float] = None
    is_day: Optional[bool] = None
    daylight_seconds: Optional[int] = None


class HourlyPoint(BaseModel):
    time: str
    temperature: Optional[float] = None
    feels_like: Optional[float] = None
    precipitation_probability: Optional[int] = None
    precipitation: Optional[float] = None
    weather_code: Optional[int] = None
    weather_label: Optional[str] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[int] = None
    humidity: Optional[int] = None
    uv_index: Optional[float] = None
    visibility: Optional[float] = None
    cloud_cover: Optional[int] = None
    is_day: Optional[int] = None


class DailyPoint(BaseModel):
    date: str
    weather_code: Optional[int] = None
    weather_label: Optional[str] = None
    temperature_max: Optional[float] = None
    temperature_min: Optional[float] = None
    apparent_temperature_max: Optional[float] = None
    apparent_temperature_min: Optional[float] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    daylight_seconds: Optional[int] = None
    uv_index_max: Optional[float] = None
    precipitation_sum: Optional[float] = None
    precipitation_probability_max: Optional[int] = None
    wind_speed_max: Optional[float] = None
    wind_direction: Optional[int] = None


class WeatherBundle(BaseModel):
    """Everything the dashboard needs for one location."""

    location: LocationInfo
    current: CurrentWeather
    hourly: list[HourlyPoint] = Field(default_factory=list)
    daily: list[DailyPoint] = Field(default_factory=list)
    units: Units = Field(default_factory=Units)
    provider: ProviderInfo
    timezone: Optional[str] = None
    utc_offset_seconds: Optional[int] = None
    elevation: Optional[float] = None
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)


class GeocodeResult(BaseModel):
    results: list[LocationInfo] = Field(default_factory=list)
    query: str = ""


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------


class RadarFrame(BaseModel):
    time: int
    timestamp: str
    path: str
    tile_url_template: str
    is_forecast: bool = False


class RadarResponse(BaseModel):
    provider: str
    host: str
    generated_at: Optional[str] = None
    past: list[RadarFrame] = Field(default_factory=list)
    nowcast: list[RadarFrame] = Field(default_factory=list)
    satellite: list[RadarFrame] = Field(default_factory=list)
    max_zoom: int = 7
    color_scheme: str = "4"
    options: str = "0_1"
    attribution: str = "Radar data by RainViewer"
    notes: list[str] = Field(default_factory=list)


class MapLayerConfig(BaseModel):
    """Describes which real tile layers the map can render right now."""

    id: str
    label: str
    kind: str  # "raster" | "none"
    available: bool
    provider: str
    url_template: Optional[str] = None
    opacity_default: float = 0.75
    requires_api_key: bool = False
    config_var: Optional[str] = None
    legend: Optional[list[dict[str, Any]]] = None
    unavailable_reason: Optional[str] = None


class MapLayersResponse(BaseModel):
    layers: list[MapLayerConfig]
    attribution: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class WeatherAlert(BaseModel):
    id: str
    event: str
    headline: Optional[str] = None
    severity: Optional[str] = None
    certainty: Optional[str] = None
    urgency: Optional[str] = None
    area_description: Optional[str] = None
    effective: Optional[str] = None
    onset: Optional[str] = None
    expires: Optional[str] = None
    ends: Optional[str] = None
    description: Optional[str] = None
    instruction: Optional[str] = None
    sender_name: Optional[str] = None
    sent: Optional[str] = None
    source: str = "US National Weather Service"
    source_url: Optional[str] = None


class AlertsResponse(BaseModel):
    supported: bool
    provider: str
    coverage_note: Optional[str] = None
    updated_at: Optional[str] = None
    alerts: list[WeatherAlert] = Field(default_factory=list)
    count: int = 0
    stale: bool = False


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    location: Optional[LocationInfo] = None
    units: str = "metric"


class ChatCard(BaseModel):
    """A piece of retrieved data the UI can render inline.

    The assistant's text answer is backed by the same payload that was sent
    to the model, so the chat can show real numbers, a forecast strip or an
    official alert next to the prose instead of asking the user to trust it.
    """

    kind: str  # current | hourly | daily | alerts | radar | compare
    title: str
    location: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class ChatAction(BaseModel):
    """A tappable button attached to an assistant answer."""

    label: str
    kind: str  # navigate | ask | focus_location
    value: str
    payload: Optional[dict[str, Any]] = None


class ChatResponse(BaseModel):
    reply: str
    model: str
    tools_used: list[str] = Field(default_factory=list)
    provider: str = "Anthropic"
    usage: Optional[dict[str, Any]] = None
    retrieved_at: str
    cards: list[ChatCard] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    actions: list[ChatAction] = Field(default_factory=list)
    focus_location: Optional[LocationInfo] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    providers: dict[str, Any]
    timestamp: str


# ---------------------------------------------------------------------------
# Upstream validation models (Open-Meteo)
# ---------------------------------------------------------------------------


class _Upstream(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OMCurrent(_Upstream):
    time: str
    interval: Optional[int] = None
    temperature_2m: Optional[float] = None
    relative_humidity_2m: Optional[float] = None
    apparent_temperature: Optional[float] = None
    is_day: Optional[int] = None
    precipitation: Optional[float] = None
    rain: Optional[float] = None
    showers: Optional[float] = None
    snowfall: Optional[float] = None
    weather_code: Optional[int] = None
    cloud_cover: Optional[int] = None
    pressure_msl: Optional[float] = None
    surface_pressure: Optional[float] = None
    wind_speed_10m: Optional[float] = None
    wind_direction_10m: Optional[int] = None
    wind_gusts_10m: Optional[float] = None


class OMHourly(_Upstream):
    time: list[str] = Field(default_factory=list)
    temperature_2m: list[Optional[float]] = Field(default_factory=list)
    apparent_temperature: list[Optional[float]] = Field(default_factory=list)
    relative_humidity_2m: list[Optional[int]] = Field(default_factory=list)
    precipitation_probability: list[Optional[int]] = Field(default_factory=list)
    precipitation: list[Optional[float]] = Field(default_factory=list)
    weather_code: list[Optional[int]] = Field(default_factory=list)
    cloud_cover: list[Optional[int]] = Field(default_factory=list)
    visibility: list[Optional[float]] = Field(default_factory=list)
    wind_speed_10m: list[Optional[float]] = Field(default_factory=list)
    wind_direction_10m: list[Optional[int]] = Field(default_factory=list)
    uv_index: list[Optional[float]] = Field(default_factory=list)
    is_day: list[Optional[int]] = Field(default_factory=list)


class OMDaily(_Upstream):
    time: list[str] = Field(default_factory=list)
    weather_code: list[Optional[int]] = Field(default_factory=list)
    temperature_2m_max: list[Optional[float]] = Field(default_factory=list)
    temperature_2m_min: list[Optional[float]] = Field(default_factory=list)
    apparent_temperature_max: list[Optional[float]] = Field(default_factory=list)
    apparent_temperature_min: list[Optional[float]] = Field(default_factory=list)
    sunrise: list[Optional[str]] = Field(default_factory=list)
    sunset: list[Optional[str]] = Field(default_factory=list)
    daylight_duration: list[Optional[float]] = Field(default_factory=list)
    uv_index_max: list[Optional[float]] = Field(default_factory=list)
    precipitation_sum: list[Optional[float]] = Field(default_factory=list)
    precipitation_probability_max: list[Optional[int]] = Field(default_factory=list)
    wind_speed_10m_max: list[Optional[float]] = Field(default_factory=list)
    wind_direction_10m_dominant: list[Optional[int]] = Field(default_factory=list)


class OMUnits(_Upstream):
    temperature_2m: Optional[str] = None
    wind_speed_10m: Optional[str] = None
    precipitation: Optional[str] = None
    visibility: Optional[str] = None
    pressure_msl: Optional[str] = None
    relative_humidity_2m: Optional[str] = None
    cloud_cover: Optional[str] = None
    uv_index: Optional[str] = None
    time: Optional[str] = None


class OpenMeteoResponse(_Upstream):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    elevation: Optional[float] = None
    timezone: Optional[str] = None
    timezone_abbreviation: Optional[str] = None
    utc_offset_seconds: Optional[int] = None
    generationtime_ms: Optional[float] = None
    current: Optional[OMCurrent] = None
    current_units: Optional[OMUnits] = None
    hourly: Optional[OMHourly] = None
    hourly_units: Optional[OMUnits] = None
    daily: Optional[OMDaily] = None
    daily_units: Optional[OMUnits] = None
    reason: Optional[str] = None
    error: Optional[bool] = None


# ---------------------------------------------------------------------------
# Upstream validation models (geocoding / radar / NWS)
# ---------------------------------------------------------------------------


class GeoResult(_Upstream):
    id: Optional[int] = None
    name: str
    latitude: float
    longitude: float
    elevation: Optional[float] = None
    feature_code: Optional[str] = None
    country_code: Optional[str] = None
    country: Optional[str] = None
    admin1: Optional[str] = None
    admin2: Optional[str] = None
    timezone: Optional[str] = None
    population: Optional[int] = None


class GeoResponse(_Upstream):
    results: list[GeoResult] = Field(default_factory=list)
    generationtime_ms: Optional[float] = None


class RadarFrameRaw(_Upstream):
    time: int
    path: str


class RadarSatelliteRaw(_Upstream):
    infrared: list[RadarFrameRaw] = Field(default_factory=list)


class RadarRaw(_Upstream):
    past: list[RadarFrameRaw] = Field(default_factory=list)
    nowcast: list[RadarFrameRaw] = Field(default_factory=list)


class WeatherMapsRaw(_Upstream):
    version: Optional[str] = None
    generated: Optional[int] = None
    host: Optional[str] = None
    radar: Optional[RadarRaw] = None
    satellite: Optional[RadarSatelliteRaw] = None


class NWSAlertProperties(_Upstream):
    id: Optional[str] = None
    areaDesc: Optional[str] = None
    severity: Optional[str] = None
    certainty: Optional[str] = None
    urgency: Optional[str] = None
    event: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    instruction: Optional[str] = None
    effective: Optional[str] = None
    onset: Optional[str] = None
    expires: Optional[str] = None
    ends: Optional[str] = None
    sent: Optional[str] = None
    senderName: Optional[str] = None
    sentFrom: Optional[str] = None
    parameters: Optional[dict[str, Any]] = None


class NWSAlertFeature(_Upstream):
    id: Optional[str] = None
    properties: Optional[NWSAlertProperties] = None


class NWSAlertsResponse(_Upstream):
    features: list[NWSAlertFeature] = Field(default_factory=list)
    updated: Optional[str] = None
    title: Optional[str] = None
