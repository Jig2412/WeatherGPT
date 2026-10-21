"""Application configuration loaded from environment variables / .env files."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Only ``ANTHROPIC_API_KEY`` is strictly required for the AI assistant.
    Every other data source used by default (Open-Meteo, RainViewer public tier,
    US National Weather Service, BigDataCloud reverse geocoding) is keyless.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "WeatherGPT API"
    version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 3001

    # Comma separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    # --- Anthropic (AI assistant) -------------------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_max_tokens: int = 2048

    # --- OpenWeatherMap (OPTIONAL map tile layers: temp / wind / clouds) ----
    # Without this key the precipitation radar layer still works (RainViewer),
    # but the optional OWM raster layers stay disabled instead of faking data.
    weather_api_key: str | None = None
    weather_tile_base: str = "https://tile.openweathermap.org/map"

    # --- RainViewer (radar) -------------------------------------------------
    # The public tier works keyless. Set this only if you have a commercial key.
    radar_api_key: str | None = None
    radar_api_base: str = "https://api.rainviewer.com/public"
    radar_tile_base: str = "https://tilecache.rainviewer.com"

    # --- Other keyless providers -------------------------------------------
    open_meteo_base: str = "https://api.open-meteo.com/v1"
    geocoding_base: str = "https://geocoding-api.open-meteo.com/v1"
    nws_alerts_base: str = "https://api.weather.gov/alerts"
    reverse_geo_url: str = "https://api.bigdatacloud.net/data/reverse-geocode-client"

    # Identify yourself to APIs that require a contact (NWS mandates this).
    weather_contact_email: str | None = None

    # Fallback coordinates used when the client has not chosen a location yet.
    default_lat: float = 28.6139
    default_lon: float = 77.209

    # Cache lifetimes (seconds).
    cache_ttl_weather: int = 60
    cache_ttl_geocode: int = 600
    cache_ttl_radar: int = 240
    cache_ttl_alerts: int = 120

    # Simple in-process throttle for the AI endpoint (requests per minute per IP).
    chat_rate_limit_per_minute: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def user_agent(self) -> str:
        """Contact string sent to providers that mandate a User-Agent."""
        if self.weather_contact_email:
            return f"WeatherGPT/1.0 ({self.weather_contact_email})"
        return "WeatherGPT/1.0 (open-source demo application)"

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.strip())

    @property
    def has_weather_key(self) -> bool:
        return bool(self.weather_api_key and self.weather_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
