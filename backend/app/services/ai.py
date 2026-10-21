"""Anthropic Claude integration for the AI weather assistant.

The assistant is given *tools* that hit the same real providers the rest of the
app uses (Open-Meteo, Open-Meteo Geocoding, US National Weather Service,
RainViewer). Claude must call a tool before it can talk about weather, so the
answers are grounded in retrieved data instead of the model's memory.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AsyncAnthropic,
    RateLimitError,
)

from ..config import get_settings
from ..errors import MissingConfigError, UpstreamError
from ..schemas import ChatAction, ChatCard, ChatResponse, LocationInfo
from . import alerts as alerts_service
from . import geocoding
from . import open_meteo
from . import radar as radar_service

MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT = """You are WeatherGPT, the assistant inside a real-time weather dashboard.

ABSOLUTE RULES
1. Answer weather questions ONLY from tool results you fetched in this conversation. Never answer from memory, never estimate a reading, never fabricate a value, a radar observation, or an official alert.
2. Before answering anything about current conditions, a forecast, rain, temperature, wind, UV, visibility, sunrise/sunset, radar or alerts, call the matching tool first. If the question is about a city that is not in the context you were given, use search_locations to resolve the name, then fetch data for it.
3. Always say where the data came from and give the relevant timestamps. Specifically:
   - Open-Meteo "current" values are numerical weather model analysis/estimates for the grid cell containing the point. They are NOT a live reading from a weather station. Say "model estimate" rather than "observation" when it matters.
   - RainViewer frames are observed radar composites; the public tier publishes past frames only, with no nowcast.
   - Official alerts come only from the get_official_alerts tool (US National Weather Service) and exist only for points inside the United States. If the tool says coverage is unavailable, say so plainly.
4. If a tool returns an error or no data, state that the information is unavailable and why. Never fill the gap with assumptions.
5. Compare cities only using data fetched for each city.
6. Use the units supplied in the tool results and keep them consistent.
7. Keep the user's selected location in mind, but never assume the question is about it if they clearly name another place.

HOW TO ANSWER LIKE A WEATHER ASSISTANT
- Lead with the direct answer in the first sentence: "Yes, expect rain around 4 PM" / "It is 18°C and clear right now", not with a restatement of the question.
- Give the concrete numbers that support the answer (temperature, precipitation chance and amount, wind, times), not a generic description.
- For advice questions ("should I carry an umbrella", "good day for a run"), give a clear recommendation plus the two or three values that justify it.
- For multi-hour or multi-day questions use a short Markdown table or bullet list with times and values.
- Name the place you are talking about so the answer stays unambiguous.
- The interface renders your tool data as cards next to your text, so do not repeat a full table of raw numbers that the card already shows. Summarise in prose and highlight the parts that matter.
- Keep it tight: one to three short paragraphs, or a small table, or short bullet lists.
- Do not add disclaimers about being an AI model."""


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_locations",
        "description": "Find the latitude/longitude of a place by name. Use this before any other weather tool when the user names a city you do not have coordinates for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Place name to look up, e.g. 'Mumbai'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_current_weather",
        "description": "Current weather conditions (temperature, feels-like, humidity, wind, precipitation, cloud cover, UV, visibility) for a place.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Place name, e.g. 'Delhi, India'."},
                "units": {"type": "string", "enum": ["metric", "imperial"], "description": "Unit system. Default metric."},
            },
            "required": ["location"],
        },
    },
    {
        "name": "get_hourly_forecast",
        "description": "Hour-by-hour forecast for a place, typically used for questions like 'will it rain in the next three hours'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "hours": {"type": "integer", "description": "How many hours ahead, default 24, max 48."},
                "units": {"type": "string", "enum": ["metric", "imperial"]},
            },
            "required": ["location"],
        },
    },
    {
        "name": "get_daily_forecast",
        "description": "Daily forecast for a place, typically used for questions about tomorrow or the coming week.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "days": {"type": "integer", "description": "How many days ahead, default 7, max 16."},
                "units": {"type": "string", "enum": ["metric", "imperial"]},
            },
            "required": ["location"],
        },
    },
    {
        "name": "compare_locations",
        "description": "Current conditions for several places side by side. Use for comparison questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Two or more place names.",
                },
                "units": {"type": "string", "enum": ["metric", "imperial"]},
            },
            "required": ["locations"],
        },
    },
    {
        "name": "get_official_alerts",
        "description": "Official weather warnings for a place. Only the US National Weather Service feed is configured, so this works for US locations only.",
        "input_schema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
    {
        "name": "get_radar_status",
        "description": "Radar availability and the timestamp of the newest observed radar frame. Returns metadata only, not imagery.",
        "input_schema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_messages(raw: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Coerce arbitrary client history into a valid Anthropic message list."""
    messages: list[dict[str, Any]] = []
    for item in raw:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + content
        else:
            messages.append({"role": role, "content": content})

    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)

    if not messages:
        messages = [{"role": "user", "content": "Give me a short weather summary."}]
    return messages


async def _resolve(name: str) -> Optional[LocationInfo]:
    return await geocoding.resolve_location(name)


def _location_payload(location: LocationInfo) -> dict[str, Any]:
    return {
        "name": location.name,
        "admin1": location.admin1,
        "country": location.country,
        "country_code": location.country_code,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": location.timezone,
    }


def _provider_payload(bundle: open_meteo.WeatherBundle) -> dict[str, Any]:
    provider = bundle.provider
    return {
        "name": provider.name,
        "data_kind": provider.data_kind,
        "is_live_observation": provider.is_live_observation,
        "is_model_based": provider.is_model_based,
        "retrieved_at": provider.retrieved_at,
        "generated_at": provider.generated_at,
        "observation_time": provider.observation_time,
        "note": provider.note,
    }


def _weather_card(
    kind: str,
    bundle: open_meteo.WeatherBundle,
    hours: int,
    days: int,
) -> ChatCard:
    """Turn a fetched bundle into a card the chat UI can render."""
    location = bundle.location
    label = location.label
    units = bundle.units.model_dump()

    if kind == "current":
        current = bundle.current
        today = bundle.daily[0] if bundle.daily else None
        data: dict[str, Any] = {
            "location": _location_payload(location),
            "units": units,
            "current": {
                "observed_at": current.observed_at,
                "temperature": current.temperature,
                "feels_like": current.feels_like,
                "humidity": current.humidity,
                "precipitation": current.precipitation,
                "weather_label": current.weather_label,
                "weather_code": current.weather_code,
                "cloud_cover": current.cloud_cover,
                "wind_speed": current.wind_speed,
                "wind_direction": current.wind_direction,
                "wind_gusts": current.wind_gusts,
                "uv_index": current.uv_index,
                "visibility": current.visibility,
                "pressure_msl": current.pressure_msl,
                "is_day": current.is_day,
            },
            "today": (
                {
                    "date": today.date,
                    "weather_label": today.weather_label,
                    "temperature_max": today.temperature_max,
                    "temperature_min": today.temperature_min,
                    "sunrise": today.sunrise,
                    "sunset": today.sunset,
                }
                if today
                else None
            ),
            "provider": _provider_payload(bundle),
        }
        return ChatCard(kind="current", title=f"Current conditions · {label}", location=label, data=data)

    if kind == "hourly":
        points = bundle.hourly[: max(1, min(hours, len(bundle.hourly)))]
        data = {
            "location": _location_payload(location),
            "units": units,
            "hours": [
                {
                    "time": h.time,
                    "temperature": h.temperature,
                    "feels_like": h.feels_like,
                    "precipitation_probability": h.precipitation_probability,
                    "precipitation": h.precipitation,
                    "weather_label": h.weather_label,
                    "weather_code": h.weather_code,
                    "wind_speed": h.wind_speed,
                    "humidity": h.humidity,
                    "is_day": h.is_day,
                }
                for h in points
            ],
            "provider": _provider_payload(bundle),
        }
        return ChatCard(
            kind="hourly",
            title=f"Next {len(points)} hours · {label}",
            location=label,
            data=data,
        )

    points = bundle.daily[: max(1, min(days, len(bundle.daily)))]
    data = {
        "location": _location_payload(location),
        "units": units,
        "days": [
            {
                "date": d.date,
                "weather_label": d.weather_label,
                "weather_code": d.weather_code,
                "temperature_max": d.temperature_max,
                "temperature_min": d.temperature_min,
                "precipitation_sum": d.precipitation_sum,
                "precipitation_probability_max": d.precipitation_probability_max,
                "uv_index_max": d.uv_index_max,
                "wind_speed_max": d.wind_speed_max,
                "sunrise": d.sunrise,
                "sunset": d.sunset,
            }
            for d in points
        ],
        "provider": _provider_payload(bundle),
    }
    return ChatCard(
        kind="daily",
        title=f"{len(points)}-day forecast · {label}",
        location=label,
        data=data,
    )


async def _execute_tool(
    name: str, payload: dict[str, Any], default_units: str
) -> dict[str, Any]:
    """Run a weather tool.

    Returns the payload handed to the model plus the extras the chat UI needs:
    a renderable card and the resolved location the tool worked on.
    """
    units = payload.get("units") if payload.get("units") in ("metric", "imperial") else default_units

    def done(model_payload: dict[str, Any], card: Optional[ChatCard] = None,
             location: Optional[LocationInfo] = None) -> dict[str, Any]:
        return {"model": model_payload, "card": card, "location": location}

    if name == "search_locations":
        query = str(payload.get("query") or "").strip()
        locations = await geocoding.search_locations(query, count=5)
        return done(
            {
                "query": query,
                "matches": [
                    {
                        "name": loc.name,
                        "admin1": loc.admin1,
                        "country": loc.country,
                        "latitude": loc.latitude,
                        "longitude": loc.longitude,
                        "timezone": loc.timezone,
                    }
                    for loc in locations
                ],
                "count": len(locations),
            }
        )

    if name in {"get_current_weather", "get_hourly_forecast", "get_daily_forecast"}:
        location_name = str(payload.get("location") or "").strip()
        location = await _resolve(location_name)
        if location is None:
            return done(
                {
                    "error": f"Could not resolve '{location_name}' to a location.",
                    "location": location_name,
                }
            )
        bundle = await open_meteo.fetch_weather(
            location.latitude, location.longitude, units=units, days=7, location=location
        )
        summary = open_meteo.summarize_for_model(bundle)

        if name == "get_current_weather":
            summary.pop("hourly_next_24h", None)
            summary.pop("daily_forecast", None)
            card = _weather_card("current", bundle, hours=0, days=0)
        elif name == "get_hourly_forecast":
            hours = max(1, min(int(payload.get("hours") or 24), 48))
            summary.pop("daily_forecast", None)
            summary["hourly_next_24h"] = summary.get("hourly_next_24h", [])[:hours]
            card = _weather_card("hourly", bundle, hours=hours, days=0)
        else:
            days = max(1, min(int(payload.get("days") or 7), 16))
            summary.pop("hourly_next_24h", None)
            summary["daily_forecast"] = summary.get("daily_forecast", [])[:days]
            card = _weather_card("daily", bundle, hours=0, days=days)

        return done(summary, card, location)

    if name == "compare_locations":
        names = [str(n).strip() for n in (payload.get("locations") or []) if str(n).strip()]
        names = names[:5]
        if len(names) < 2:
            return done({"error": "Provide at least two locations to compare."})
        results = []
        card_rows = []
        card_units: Optional[dict[str, Any]] = None
        for city in names:
            location = await _resolve(city)
            if location is None:
                results.append({"requested": city, "error": "Location not found."})
                continue
            bundle = await open_meteo.fetch_weather(
                location.latitude, location.longitude, units=units, days=1, location=location
            )
            summary = open_meteo.summarize_for_model(bundle)
            results.append(
                {
                    "requested": city,
                    "resolved": f"{location.name}, {location.country or ''}".strip(", "),
                    "current": summary["current"],
                    "units": summary["units"],
                    "today": (summary.get("daily_forecast") or [{}])[0],
                    "data_kind": summary["provider"]["data_kind"],
                    "forecast_time_local": summary["provider"]["forecast_time_local"],
                }
            )
            current = bundle.current
            if card_units is None:
                card_units = bundle.units.model_dump()
            card_rows.append(
                {
                    "location": _location_payload(location),
                    "current": {
                        "observed_at": current.observed_at,
                        "temperature": current.temperature,
                        "feels_like": current.feels_like,
                        "humidity": current.humidity,
                        "precipitation": current.precipitation,
                        "weather_label": current.weather_label,
                        "weather_code": current.weather_code,
                        "wind_speed": current.wind_speed,
                        "uv_index": current.uv_index,
                        "cloud_cover": current.cloud_cover,
                    },
                    "today": (
                        {
                            "date": bundle.daily[0].date,
                            "temperature_max": bundle.daily[0].temperature_max,
                            "temperature_min": bundle.daily[0].temperature_min,
                            "weather_label": bundle.daily[0].weather_label,
                        }
                        if bundle.daily
                        else None
                    ),
                }
            )
        card = ChatCard(
            kind="compare",
            title=f"Comparing {len(card_rows)} locations",
            data={"rows": card_rows, "units": card_units or {}},
        )
        return done({"locations": results, "units": units}, card)

    if name == "get_official_alerts":
        location_name = str(payload.get("location") or "").strip()
        location = await _resolve(location_name)
        if location is None:
            return done({"error": f"Could not resolve '{location_name}' to a location."})
        response = await alerts_service.get_alerts(location.latitude, location.longitude)
        label = f"{location.name}, {location.country or ''}".strip(", ")
        model_payload = {
            "location": label,
            "supported": response.supported,
            "provider": response.provider,
            "coverage_note": response.coverage_note,
            "updated_at": response.updated_at,
            "count": response.count,
            "alerts": [
                {
                    "event": a.event,
                    "severity": a.severity,
                    "urgency": a.urgency,
                    "area": a.area_description,
                    "effective": a.effective,
                    "expires": a.expires,
                    "description": a.description,
                    "instruction": a.instruction,
                }
                for a in response.alerts
            ],
        }
        card = ChatCard(
            kind="alerts",
            title=f"Official alerts · {label}",
            location=label,
            data={
                "supported": response.supported,
                "provider": response.provider,
                "coverage_note": response.coverage_note,
                "updated_at": response.updated_at,
                "count": response.count,
                "alerts": [
                    {
                        "id": a.id,
                        "event": a.event,
                        "headline": a.headline,
                        "severity": a.severity,
                        "urgency": a.urgency,
                        "area_description": a.area_description,
                        "effective": a.effective,
                        "expires": a.expires,
                        "description": a.description,
                        "instruction": a.instruction,
                        "source": a.source,
                        "source_url": a.source_url,
                    }
                    for a in response.alerts
                ],
            },
        )
        return done(model_payload, card, location)

    if name == "get_radar_status":
        frames = await radar_service.get_radar_frames()
        newest = frames.past[-1] if frames.past else None
        model_payload = {
            "provider": frames.provider,
            "available_frames": len(frames.past),
            "newest_frame_time_utc": newest.timestamp if newest else None,
            "nowcast_available": bool(frames.nowcast),
            "notes": frames.notes,
            "attribution": frames.attribution,
        }
        card = ChatCard(
            kind="radar",
            title="Radar availability",
            data={
                "provider": frames.provider,
                "available_frames": len(frames.past),
                "newest_frame_time_utc": newest.timestamp if newest else None,
                "nowcast_available": bool(frames.nowcast),
                "notes": frames.notes,
                "attribution": frames.attribution,
            },
        )
        return done(model_payload, card)

    return done({"error": f"Unknown tool '{name}'."})


def _blocks_to_dicts(blocks: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        if hasattr(block, "model_dump"):
            data = block.model_dump(exclude_none=True)
        elif isinstance(block, dict):
            data = {k: v for k, v in block.items() if v is not None}
        else:  # pragma: no cover - defensive
            continue
        out.append(data)
    return out


def _build_suggestions(tools: list[str], place: Optional[str]) -> list[str]:
    """Follow-up questions the user can tap, chosen from what was retrieved."""
    where = place or "there"
    pool: list[str] = []

    if "get_current_weather" in tools:
        pool.append(f"What should I wear in {where} today?")
        pool.append(f"Is it a good time to go out in {where}?")
    if "get_hourly_forecast" in tools:
        pool.append(f"Will it rain in {where} in the next 3 hours?")
        pool.append(f"How windy does it get in {where} this afternoon?")
    if "get_daily_forecast" in tools:
        pool.append(f"Will it rain in {where} tomorrow?")
        pool.append(f"Which day this week is best for outdoor plans in {where}?")
    if "get_official_alerts" in tools:
        pool.append(f"Summarise the official warnings for {where}")
    if "get_radar_status" in tools:
        pool.append(f"Is there rain on radar near {where}?")
    if "compare_locations" in tools:
        pool.append("Which of those cities is warmest right now?")
        pool.append("Which of those cities has the best weather today?")

    if not pool:
        pool = [
            f"What is the current weather in {where}?",
            f"Will it rain in {where} tomorrow?",
        ]

    # Keep the list short and free of duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for item in pool:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:4]


def _build_actions(tools: list[str]) -> list[ChatAction]:
    """Buttons that take the user straight to the relevant screen."""
    actions: list[ChatAction] = []
    if "get_current_weather" in tools or "get_hourly_forecast" in tools:
        actions.append(ChatAction(label="7-day forecast", kind="navigate", value="/forecast"))
    if "get_radar_status" in tools:
        actions.append(ChatAction(label="Live radar", kind="navigate", value="/maps"))
    if "get_official_alerts" in tools:
        actions.append(ChatAction(label="Official alerts", kind="navigate", value="/alerts"))
    if "compare_locations" in tools:
        actions.append(ChatAction(label="Compare cities", kind="navigate", value="/compare"))
    if not actions:
        actions.append(ChatAction(label="Open dashboard", kind="navigate", value="/"))
    return actions[:3]


async def run_chat(
    messages: list[dict[str, str]],
    *,
    location: Optional[LocationInfo] = None,
    units: str = "metric",
) -> ChatResponse:
    settings = get_settings()
    if not settings.has_anthropic_key:
        raise MissingConfigError(
            "The AI assistant is not configured. Set the ANTHROPIC_API_KEY environment "
            "variable in backend/.env and restart the server.",
            provider="Anthropic",
        )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    system = SYSTEM_PROMPT
    if location is not None:
        system += (
            f"\n\nCURRENT CONTEXT\nThe user's currently selected location is "
            f"{location.name}"
            + (f", {location.admin1}" if location.admin1 else "")
            + (f", {location.country}" if location.country else "")
            + f" (lat {location.latitude:.4f}, lon {location.longitude:.4f}). "
            f"Unit preference: {units}."
        )

    conversation = _normalize_messages(messages)
    tools_used: list[str] = []
    cards: list[ChatCard] = []
    focus_location: Optional[LocationInfo] = None

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                system=system,
                messages=conversation,
                tools=TOOLS,
            )

            if response.stop_reason != "tool_use":
                text = "".join(
                    block.text for block in response.content if getattr(block, "type", "") == "text"
                ).strip()
                usage = getattr(response, "usage", None)
                place = focus_location.label if focus_location else (
                    location.label if location else None
                )
                return ChatResponse(
                    reply=text or "I could not produce an answer for that question.",
                    model=response.model,
                    tools_used=tools_used,
                    provider="Anthropic",
                    usage=(
                        {
                            "input_tokens": getattr(usage, "input_tokens", None),
                            "output_tokens": getattr(usage, "output_tokens", None),
                        }
                        if usage
                        else None
                    ),
                    retrieved_at=_now_iso(),
                    cards=cards,
                    suggestions=_build_suggestions(tools_used, place),
                    actions=_build_actions(tools_used),
                    focus_location=focus_location,
                )

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                tools_used.append(block.name)
                try:
                    outcome = await _execute_tool(block.name, dict(block.input or {}), units)
                except Exception as exc:  # tool failure is reported to the model, not fatal
                    outcome = {
                        "model": {"error": f"{exc.__class__.__name__}: {exc}"},
                        "card": None,
                        "location": None,
                    }

                result = outcome.get("model") or {}
                card = outcome.get("card")
                tool_location = outcome.get("location")

                if card is not None:
                    cards.append(card)
                if tool_location is not None:
                    focus_location = tool_location

                is_error = isinstance(result, dict) and "error" in result
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                        "is_error": is_error,
                    }
                )

            conversation = (
                conversation
                + [{"role": "assistant", "content": _blocks_to_dicts(response.content)}]
                + [{"role": "user", "content": tool_results}]
            )

        place = focus_location.label if focus_location else (
            location.label if location else None
        )
        return ChatResponse(
            reply=(
                "I gathered a lot of data for that question and could not finish the "
                "summary. Please try rephrasing or ask about a specific place."
            ),
            model=settings.anthropic_model,
            tools_used=tools_used,
            provider="Anthropic",
            retrieved_at=_now_iso(),
            cards=cards,
            suggestions=_build_suggestions(tools_used, place),
            actions=_build_actions(tools_used),
            focus_location=focus_location,
        )

    except RateLimitError as exc:
        raise UpstreamError(
            "Anthropic",
            "The Anthropic API rate limit was reached. Please wait a moment and try again.",
            status_code=429,
            code="rate_limited",
            retry_after=30,
        ) from exc
    except APIStatusError as exc:
        status = getattr(exc, "status_code", 502)
        if status in (401, 403):
            message = (
                "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in backend/.env."
            )
        elif status == 529:
            message = "Anthropic is temporarily overloaded. Please try again shortly."
        else:
            message = f"Anthropic returned HTTP {status}: {exc}"
        raise UpstreamError(
            "Anthropic", message, status_code=502, code="anthropic_error"
        ) from exc
    except APIConnectionError as exc:
        raise UpstreamError(
            "Anthropic",
            "Could not reach the Anthropic API. Please try again shortly.",
            status_code=502,
            code="upstream_unreachable",
        ) from exc
