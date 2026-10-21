# WeatherGPT — Backend

FastAPI service that fronts every upstream weather provider and the Anthropic
assistant. The frontend never talks to a third-party API directly, so no API
key is ever shipped to the browser.

## Run it

```bash
pip install -r requirements.txt
copy .env.example .env      # Windows  (macOS/Linux: cp .env.example .env)
uvicorn app.main:app --reload --port 3001
```

`backend/.env` is read automatically (`env_file=(".env", "../.env")`), so a
repo-root `.env` works too.

On Windows, `scripts\start-dev.ps1 -BackendOnly` stops any running instance and
starts a fresh one, waiting for `/api/health` before returning. Use it whenever
you edit `backend/.env` — the settings are read once at startup.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                       # everything
pytest -m "not network"      # skip the tests that hit the live providers
```

The suite stubs the Anthropic client, so **no API key is needed**. Tests marked
`network` do call the real keyless providers (Open-Meteo, NWS) to prove the
cards contain genuine data and that model analysis is never labelled as a
live observation.

## Layout

| Path | Responsibility |
| --- | --- |
| `app/main.py` | App factory, CORS middleware, router registration, global error handlers |
| `app/config.py` | `pydantic-settings` configuration + `Settings` accessors |
| `app/cache.py` | TTL cache with stale-on-error and single-flight request coalescing |
| `app/schemas.py` | Pydantic models: upstream payload validation **and** the public API contract |
| `app/errors.py` | Provider-specific exceptions mapped to HTTP status codes |
| `app/routers/weather.py` | `/api/weather/current`, `/api/weather/location`, `/api/weather/reverse` |
| `app/routers/alerts.py` | `/api/alerts` — official NWS warnings (US only) |
| `app/routers/radar.py` | `/api/radar/frames`, `/api/map/layers` |
| `app/routers/tiles.py` | `/api/map/tiles/...` — server-side tile proxy that hides the OWM key |
| `app/routers/geo.py` | `/api/geocode` |
| `app/routers/chat.py` | `/api/chat` — Anthropic assistant with per-IP rate limiting |
| `app/routers/meta.py` | `/api/health` — which providers are configured |
| `app/services/open_meteo.py` | Open-Meteo forecast client, WMO code mapping, model summaries |
| `app/services/geocoding.py` | Open-Meteo Geocoding client |
| `app/services/alerts.py` | NWS alerts client + coverage detection |
| `app/services/radar.py` | RainViewer frame discovery |
| `app/services/reverse_geo.py` | BigDataCloud reverse geocoding |
| `app/services/ai.py` | Claude tool loop, card building, suggestions and actions |
| `app/services/http.py` | Shared `httpx` client, timeouts and upstream error mapping |

## Design notes

**Upstream payloads are validated separately from the public contract.**
`O*` models in `schemas.py` mirror the raw provider JSON, where every optional
field is `Optional[...]` because Open-Meteo legitimately returns `null`. The
public models are the stable shape the frontend consumes.

**`current` is model analysis, not an observation.** `ProviderInfo.is_live_observation`
is always `False` for Open-Meteo data, and the frontend labels it accordingly.
RainViewer frames *are* observations and are marked as such.

**Alerts degrade honestly.** Outside the United States the NWS endpoint returns
`supported: false` with a `coverage_note` explaining the gap. The service never
substitutes a synthetic warning.

**The cache coalesces.** `TTLCache.get_or_set` keeps one in-flight task per
key, so concurrent identical requests share a single upstream call. When the
producer fails, an expired value is returned with `stale=True` and the frontend
flags it.

## The assistant (`app/services/ai.py`)

```
user message
   │
   ├─▶ Claude (system prompt + tools)
   │      │
   │      ├─ tool_use  ──▶ _execute_tool() ──▶ { model payload, card, location }
   │      │                     │
   │      │                     ├─ model payload ──▶ back to Claude as tool_result
   │      │                     └─ card / location ──▶ accumulated for the response
   │      │
   │      └─ end_turn  ──▶ prose answer
   │
   └─▶ ChatResponse { reply, cards, suggestions, actions, focus_location }
```

- `MAX_TOOL_ITERATIONS = 8` bounds the loop.
- A failing tool is reported to the model as an error result rather than
  aborting the request, so the assistant can explain what went wrong.
- Cards are generated from the same objects that were sent to the model.
- `focus_location` is the place the answer is actually about — the frontend
  uses it to offer "Switch app to <city>".

## Environment variables

Only `ANTHROPIC_API_KEY` is required.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | **Required** for `/api/chat` |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Claude model id |
| `ANTHROPIC_MAX_TOKENS` | `2048` | Max output tokens per reply |
| `WEATHER_API_KEY` | — | Optional OpenWeatherMap key for the raster map layers |
| `WEATHER_RADAR_API_KEY` | — | Optional commercial RainViewer key |
| `HOST` / `PORT` | `0.0.0.0` / `3001` | Bind address |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed browser origins |
| `WEATHER_CONTACT_EMAIL` | — | Contact address for the User-Agent (NWS requires it) |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `20` | Per-IP chat throttle |
| `CACHE_TTL_WEATHER` | `60` | Weather cache TTL (seconds) |
| `CACHE_TTL_GEOCODE` | `600` | Geocoding cache TTL |
| `CACHE_TTL_RADAR` | `240` | Radar frame cache TTL |
| `CACHE_TTL_ALERTS` | `120` | Alert cache TTL |

## Adding a provider

1. Write a service module in `app/services/` that returns validated `O*`
   models.
2. Add the endpoint in `app/routers/`, or expose it as a tool in
   `app/services/ai.py` (`TOOLS` + a branch in `_execute_tool`).
3. Register it in `app/services/meta.py` so `/api/health` reports its status.
4. Mirror the new shape in `frontend/src/types/weather.ts`.

## Attribution requirements

- RainViewer tiles **must** display "Radar data by RainViewer".
- The US National Weather Service requires an identifying `User-Agent`; set
  `WEATHER_CONTACT_EMAIL` for production deployments.
