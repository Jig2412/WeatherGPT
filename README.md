# WeatherGPT — Frontend

React 19 + Vite + TypeScript + Tailwind CSS v4. The browser never talks to a
third-party weather API — every request goes to the FastAPI backend through
`/api`, so no provider key is ever exposed here.

## Run it

```bash
npm install
npm run dev
```

Open <http://localhost:5173>.

> Use `localhost`, not `127.0.0.1` — the dev server binds to the `localhost`
> hostname only.

The dev server proxies `/api` to `http://127.0.0.1:3001` (see `vite.config.ts`).

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Dev server with HMR on port 5173 |
| `npm run build` | `tsc -b` type-check + production build to `dist/` |
| `npm run lint` | Oxlint |
| `npm run preview` | Serve the production build locally |

## Configuration

Copy `.env.example` to `.env`. Everything is optional:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `""` | Absolute backend API base, **including `/api`**. Leave empty to use the dev proxy |
| `VITE_BACKEND_URL` | `http://127.0.0.1:3001` | Where the dev proxy forwards `/api` |

> Never put `ANTHROPIC_API_KEY` or `WEATHER_API_KEY` here. Anything prefixed
> with `VITE_` is bundled into the browser and is public.

## Layout

```
src/
├── components/
│   ├── chat/        # ChatDataCard, QuickActions, FollowUpChips
│   ├── common/      # WeatherIcon, Panel, States (Spinner, ErrorBanner, …)
│   ├── dashboard/   # hero card, stat tiles, hourly strip, charts
│   ├── forecast/    # hourly + daily tables
│   └── map/         # Leaflet map, layer switcher, radar controls
├── context/         # AppContext (units, location, favourites, refresh), WeatherContext
├── hooks/           # useWeather, useCityWeather, useAlerts, useRadar, useChat, useVoiceInput
├── lib/             # api client, formatters, weather codes, RequestSlot, payload helpers
├── pages/           # Dashboard, Maps, Forecast, Chat, Compare, Saved, Alerts, Settings
├── types/           # TypeScript mirror of backend/app/schemas.py
└── App.tsx          # layout, sidebar, top bar, routes
```

## Conventions

- **API logic lives in hooks**, never inside components. Components receive
  data and render it.
- **`types/weather.ts` mirrors `backend/app/schemas.py`.** Change one, change
  the other.
- **Untyped payloads are narrowed with `lib/payload.ts`** (`asRecord`,
  `asNumber`, `child`, …) rather than casting inline.
- **Requests go through `lib/RequestSlot.ts`**, which aborts the previous
  request and guards against out-of-order responses. Use it for any new
  fetching hook — the plain `AbortController` alone is not enough under React
  StrictMode, which mounts effects twice in development.
- **Every provider timestamp is surfaced** in the UI. Never label a model
  estimate as a live observation.
