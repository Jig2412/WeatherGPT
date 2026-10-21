"""WMO weather interpretation codes used by Open-Meteo."""
from __future__ import annotations

WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "clear"),
    1: ("Mainly clear", "mainly_clear"),
    2: ("Partly cloudy", "partly_cloudy"),
    3: ("Overcast", "overcast"),
    45: ("Fog", "fog"),
    48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Moderate drizzle", "drizzle"),
    55: ("Dense drizzle", "drizzle"),
    56: ("Light freezing drizzle", "sleet"),
    57: ("Dense freezing drizzle", "sleet"),
    61: ("Slight rain", "rain"),
    63: ("Moderate rain", "rain"),
    65: ("Heavy rain", "heavy_rain"),
    66: ("Light freezing rain", "sleet"),
    67: ("Heavy freezing rain", "sleet"),
    71: ("Slight snowfall", "snow"),
    73: ("Moderate snowfall", "snow"),
    75: ("Heavy snowfall", "heavy_snow"),
    77: ("Snow grains", "snow"),
    80: ("Slight rain showers", "showers"),
    81: ("Moderate rain showers", "showers"),
    82: ("Violent rain showers", "heavy_rain"),
    85: ("Slight snow showers", "snow"),
    86: ("Heavy snow showers", "heavy_snow"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm with slight hail", "thunderstorm"),
    99: ("Thunderstorm with heavy hail", "thunderstorm"),
}


def describe(code: int | None) -> str | None:
    if code is None:
        return None
    entry = WMO_CODES.get(int(code))
    return entry[0] if entry else f"Unknown code {code}"


def icon_for(code: int | None, is_day: bool = True) -> str:
    if code is None:
        return "unknown"
    entry = WMO_CODES.get(int(code))
    if not entry:
        return "unknown"
    kind = entry[1]
    if kind in ("clear", "mainly_clear"):
        return "clear-day" if is_day else "clear-night"
    if kind == "partly_cloudy":
        return "partly-cloudy-day" if is_day else "partly-cloudy-night"
    return kind
