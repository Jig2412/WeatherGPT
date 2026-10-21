"""Official weather alerts.

The only alert feed published by a government weather service that can be
consumed without an API key is the US National Weather Service (api.weather.gov).
That feed is strictly geographic to the United States. For any other location
the API reports ``supported: false`` with an explanation -- the app never
renders a fabricated warning.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..config import get_settings
from ..errors import UpstreamError
from ..schemas import AlertsResponse, NWSAlertFeature, NWSAlertsResponse, WeatherAlert
from .http import build_client, get_json

PROVIDER = "US National Weather Service (NOAA)"
NOT_COVERED_NOTE = (
    "Official alert coverage is currently limited to the United States, where the "
    "National Weather Service publishes machine-readable watches, warnings and "
    "advisories. No equivalent keyless official feed is configured for this "
    "location, so no official warnings can be displayed here."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_feature(feature: NWSAlertFeature) -> Optional[WeatherAlert]:
    props = feature.properties
    if props is None:
        return None
    event = props.event or "Weather Alert"
    return WeatherAlert(
        id=props.id or feature.id or event,
        event=event,
        headline=props.headline,
        severity=props.severity,
        certainty=props.certainty,
        urgency=props.urgency,
        area_description=props.areaDesc,
        effective=props.effective,
        onset=props.onset,
        expires=props.expires,
        ends=props.ends,
        description=props.description,
        instruction=props.instruction,
        sender_name=props.senderName or PROVIDER,
        sent=props.sent,
        source=PROVIDER,
        source_url=props.id or feature.id,
    )


async def get_alerts(latitude: float, longitude: float) -> AlertsResponse:
    settings = get_settings()
    url = f"{settings.nws_alerts_base}/active"
    params = {"point": f"{latitude:.4f},{longitude:.4f}"}

    async with build_client() as client:
        try:
            payload = await get_json(
                client,
                url,
                provider=PROVIDER,
                params=params,
                headers={"User-Agent": settings.user_agent, "Accept": "application/geo+json"},
            )
        except UpstreamError as exc:
            message = exc.message.lower()
            if "out of bounds" in message or "invalid parameter" in message:
                # NWS only covers the United States (plus nearby marine areas).
                return AlertsResponse(
                    supported=False,
                    provider=PROVIDER,
                    coverage_note=NOT_COVERED_NOTE,
                    updated_at=_now_iso(),
                    alerts=[],
                    count=0,
                )
            raise

    try:
        data = NWSAlertsResponse.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise UpstreamError(
            PROVIDER,
            "The alert feed returned a payload that does not match the expected schema.",
            code="invalid_response",
        ) from exc

    alerts = [a for a in (_parse_feature(f) for f in data.features) if a is not None]
    alerts.sort(key=lambda a: a.sent or a.effective or "", reverse=True)

    return AlertsResponse(
        supported=True,
        provider=PROVIDER,
        coverage_note=(
            "Live official warnings issued by the US National Weather Service for "
            "this point."
        ),
        updated_at=data.updated or _now_iso(),
        alerts=alerts,
        count=len(alerts),
    )
