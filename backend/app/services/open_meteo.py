"""Open-Meteo forecast client.

Open-Meteo publishes a *model-based* forecast. Its ``current`` block is an
analysis/estimate produced by numerical weather models (not a reading from a
nearby weather station), and that distinction is preserved in the payload via
``ProviderInfo.data_kind`` / ``is_live_observation``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..config import get_settings
from ..errors import UpstreamError, ValidationError
from ..schemas import (
    CurrentWeather,
    DailyPoint,
    HourlyPoint,
    LocationInfo,
    OpenMeteoResponse,
    ProviderInfo,
    Units,
    WeatherBundle,
)
from . import weather_codes
from .http import build_client, get_json

CURRENT_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]

HOURLY_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "uv_index",
    "is_day",
]

DAILY_FIELDS = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "sunrise",
    "sunset",
    "daylight_duration",
    "uv_index_max",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_direction_10m_dominant",
]

_UNIT_PARAMS = {
    "metric": {"temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm"},
    "imperial": {
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _index_of(hourly_times: list[str], target: str | None) -> int:
    """Index of the hourly slot matching the current time (hour precision)."""
    if not hourly_times:
        return 0
    if target:
        for idx, value in enumerate(hourly_times):
            if value[:13] == target[:13]:
                return idx
    return 0


async def fetch_weather(
    latitude: float,
    longitude: float,
    *,
    units: str = "metric",
    days: int = 7,
    location: Optional[LocationInfo] = None,
) -> WeatherBundle:
    """Fetch current conditions + hourly + daily for a coordinate pair."""
    settings = get_settings()
    unit = units if units in _UNIT_PARAMS else "metric"
    days = max(1, min(int(days), 16))

    params: dict[str, Any] = {
        "latitude": round(latitude, 4),
        "longitude": round(longitude, 4),
        "current": ",".join(CURRENT_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
        "timezone": "auto",
        "forecast_days": days,
        "timeformat": "iso8601",
        **_UNIT_PARAMS[unit],
    }

    async with build_client() as client:
        payload = await get_json(
            client,
            f"{settings.open_meteo_base}/forecast",
            provider="Open-Meteo",
            params=params,
        )

    try:
        data = OpenMeteoResponse.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValidationError(
            f"Open-Meteo returned a payload that does not match the expected schema: {exc}",
            provider="Open-Meteo",
        ) from exc

    if data.current is None or data.hourly is None or data.daily is None:
        raise UpstreamError(
            "Open-Meteo",
            "Open-Meteo did not return the requested current/hourly/daily blocks.",
            code="incomplete_response",
        )

    hourly_raw = data.hourly
    daily_raw = data.daily
    current = data.current

    current_index = _index_of(hourly_raw.time, current.time)
    hour_times = hourly_raw.time[current_index : current_index + 24]

    def at(values: list[Any], offset: int) -> Any:
        """Value ``offset`` slots after the current hour inside an already sliced series."""
        values = values or []
        if 0 <= offset < len(values):
            return values[offset]
        return None

    def series(values: list[Any], count: int = 24) -> list[Any]:
        values = values or []
        return values[current_index : current_index + count]

    temps = series(hourly_raw.temperature_2m)
    feels = series(hourly_raw.apparent_temperature)
    humidity = series(hourly_raw.relative_humidity_2m)
    precip_prob = series(hourly_raw.precipitation_probability)
    precip = series(hourly_raw.precipitation)
    codes = series(hourly_raw.weather_code)
    cloud = series(hourly_raw.cloud_cover)
    visibility = series(hourly_raw.visibility)
    wind = series(hourly_raw.wind_speed_10m)
    wind_dir = series(hourly_raw.wind_direction_10m)
    uv = series(hourly_raw.uv_index)
    is_day = series(hourly_raw.is_day)

    hourly_points: list[HourlyPoint] = []
    for i, time_value in enumerate(hour_times):
        code = codes[i] if i < len(codes) else None
        hourly_points.append(
            HourlyPoint(
                time=time_value,
                temperature=temps[i] if i < len(temps) else None,
                feels_like=feels[i] if i < len(feels) else None,
                precipitation_probability=precip_prob[i] if i < len(precip_prob) else None,
                precipitation=precip[i] if i < len(precip) else None,
                weather_code=code,
                weather_label=weather_codes.describe(code),
                wind_speed=wind[i] if i < len(wind) else None,
                wind_direction=wind_dir[i] if i < len(wind_dir) else None,
                humidity=humidity[i] if i < len(humidity) else None,
                uv_index=uv[i] if i < len(uv) else None,
                visibility=visibility[i] if i < len(visibility) else None,
                cloud_cover=cloud[i] if i < len(cloud) else None,
                is_day=is_day[i] if i < len(is_day) else None,
            )
        )

    daily_points: list[DailyPoint] = []
    for i, date_value in enumerate(daily_raw.time or []):

        def daily_at(values: list[Any]) -> Any:
            values = values or []
            return values[i] if i < len(values) else None

        code = daily_at(daily_raw.weather_code)
        daylight = daily_at(daily_raw.daylight_duration)
        daily_points.append(
            DailyPoint(
                date=date_value,
                weather_code=code,
                weather_label=weather_codes.describe(code),
                temperature_max=daily_at(daily_raw.temperature_2m_max),
                temperature_min=daily_at(daily_raw.temperature_2m_min),
                apparent_temperature_max=daily_at(daily_raw.apparent_temperature_max),
                apparent_temperature_min=daily_at(daily_raw.apparent_temperature_min),
                sunrise=daily_at(daily_raw.sunrise),
                sunset=daily_at(daily_raw.sunset),
                daylight_seconds=int(daylight) if daylight is not None else None,
                uv_index_max=daily_at(daily_raw.uv_index_max),
                precipitation_sum=daily_at(daily_raw.precipitation_sum),
                precipitation_probability_max=daily_at(daily_raw.precipitation_probability_max),
                wind_speed_max=daily_at(daily_raw.wind_speed_10m_max),
                wind_direction=daily_at(daily_raw.wind_direction_10m_dominant),
            )
        )

    is_day_value = current.is_day
    day_secs = daily_points[0].daylight_seconds if daily_points else None

    current_block = CurrentWeather(
        observed_at=current.time,
        temperature=current.temperature_2m,
        feels_like=current.apparent_temperature,
        humidity=current.relative_humidity_2m,
        precipitation=current.precipitation,
        rain=current.rain,
        showers=current.showers,
        snowfall=current.snowfall,
        weather_code=current.weather_code,
        weather_label=weather_codes.describe(current.weather_code),
        cloud_cover=current.cloud_cover,
        pressure_msl=current.pressure_msl,
        surface_pressure=current.surface_pressure,
        wind_speed=current.wind_speed_10m,
        wind_direction=current.wind_direction_10m,
        wind_gusts=current.wind_gusts_10m,
        uv_index=at(uv, 0),
        visibility=at(visibility, 0),
        is_day=bool(is_day_value) if is_day_value is not None else None,
        daylight_seconds=day_secs,
    )

    loc = location or LocationInfo(
        name=f"{latitude:.3f}, {longitude:.3f}",
        latitude=latitude,
        longitude=longitude,
        source="coordinates",
    )

    units = Units(
        temperature=(data.current_units.temperature_2m if data.current_units else None) or "°C",
        wind_speed=(data.current_units.wind_speed_10m if data.current_units else None) or "km/h",
        precipitation=(data.current_units.precipitation if data.current_units else None) or "mm",
        visibility=(data.hourly_units.visibility if data.hourly_units else None) or "m",
        pressure=(data.current_units.pressure_msl if data.current_units else None) or "hPa",
        humidity=(data.current_units.relative_humidity_2m if data.current_units else None) or "%",
        cloud_cover=(data.current_units.cloud_cover if data.current_units else None) or "%",
        uv_index=(data.hourly_units.uv_index if data.hourly_units else None) or "",
        time="iso8601",
    )

    provider = ProviderInfo(
        name="Open-Meteo",
        source="Numerical weather model (NWP) output",
        data_kind="model",
        model="Best-match blend of national forecast models",
        retrieved_at=_now_iso(),
        generated_at=current.time,
        observation_time=current.time,
        is_model_based=True,
        is_live_observation=False,
        note=(
            "Current values are model analysis/estimates for the grid cell that "
            "contains the requested point, not a live reading from a weather station."
        ),
        attribution="Weather data by Open-Meteo.com",
    )

    warnings: list[str] = []
    if current.temperature_2m is None:
        warnings.append("Open-Meteo did not return a current temperature for this point.")
    if not hourly_points:
        warnings.append("Hourly forecast data is unavailable for this point.")

    return WeatherBundle(
        location=loc,
        current=current_block,
        hourly=hourly_points,
        daily=daily_points,
        units=units,
        provider=provider,
        timezone=data.timezone,
        utc_offset_seconds=data.utc_offset_seconds,
        elevation=data.elevation,
        warnings=warnings,
    )


def summarize_for_model(bundle: WeatherBundle) -> dict[str, Any]:
    """Compact, token-efficient representation handed to Claude."""
    current = bundle.current
    hourly = [
        {
            "time": h.time,
            "temperature": h.temperature,
            "precipitation_probability": h.precipitation_probability,
            "precipitation": h.precipitation,
            "weather": h.weather_label,
            "wind_speed": h.wind_speed,
            "humidity": h.humidity,
        }
        for h in bundle.hourly
    ]
    daily = [
        {
            "date": d.date,
            "weather": d.weather_label,
            "temperature_max": d.temperature_max,
            "temperature_min": d.temperature_min,
            "precipitation_sum": d.precipitation_sum,
            "precipitation_probability_max": d.precipitation_probability_max,
            "uv_index_max": d.uv_index_max,
            "wind_speed_max": d.wind_speed_max,
            "sunrise": d.sunrise,
            "sunset": d.sunset,
        }
        for d in bundle.daily
    ]
    return {
        "location": {
            "name": bundle.location.name,
            "country": bundle.location.country,
            "latitude": bundle.location.latitude,
            "longitude": bundle.location.longitude,
            "timezone": bundle.timezone,
        },
        "units": bundle.units.model_dump(),
        "current": {
            "observed_at_local": current.observed_at,
            "temperature": current.temperature,
            "feels_like": current.feels_like,
            "humidity": current.humidity,
            "precipitation": current.precipitation,
            "weather": current.weather_label,
            "cloud_cover": current.cloud_cover,
            "wind_speed": current.wind_speed,
            "wind_direction": current.wind_direction,
            "wind_gusts": current.wind_gusts,
            "uv_index": current.uv_index,
            "visibility": current.visibility,
            "pressure_msl": current.pressure_msl,
        },
        "hourly_next_24h": hourly,
        "daily_forecast": daily,
        "provider": {
            "name": bundle.provider.name,
            "data_kind": bundle.provider.data_kind,
            "is_live_observation": bundle.provider.is_live_observation,
            "retrieved_at_utc": bundle.provider.retrieved_at,
            "forecast_time_local": bundle.provider.generated_at,
            "note": bundle.provider.note,
        },
    }


def local_daylight_window(bundle: WeatherBundle) -> tuple[Optional[str], Optional[str]]:
    if not bundle.daily:
        return None, None
    today = bundle.daily[0]
    return today.sunrise, today.sunset


def hours_from_now(bundle: WeatherBundle, hours: int) -> list[HourlyPoint]:
    return bundle.hourly[: max(1, min(hours, len(bundle.hourly)))]


def days_from_now(bundle: WeatherBundle, days: int) -> list[DailyPoint]:
    return bundle.daily[: max(1, min(days, len(bundle.daily)))]


def relative_age(iso_time: str | None) -> str | None:
    """Human readable age of an ISO timestamp (UTC or local, no tz)."""
    if not iso_time:
        return None
    try:
        parsed = datetime.fromisoformat(iso_time)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "in the future"
    if seconds < 90:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    return f"{hours // 24} d ago"


def utc_offset_label(offset_seconds: int | None) -> str:
    if offset_seconds is None:
        return "UTC"
    sign = "+" if offset_seconds >= 0 else "-"
    total = abs(offset_seconds)
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def plus_hours(count: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=count)).isoformat(timespec="seconds")
