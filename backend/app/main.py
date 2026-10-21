"""WeatherGPT FastAPI application.

Run with:

    uvicorn app.main:app --reload --port 3001

from the ``backend`` directory.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .errors import register_exception_handlers
from .routers import alerts, chat, geo, meta, radar, tiles, weather

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Real-time weather API powering WeatherGPT. Forecasts and geocoding come "
        "from Open-Meteo, radar tiles from RainViewer and official alerts from the "
        "US National Weather Service. The AI assistant is powered by Anthropic Claude."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(meta.router)
app.include_router(weather.router)
app.include_router(geo.router)
app.include_router(radar.router)
app.include_router(tiles.router)
app.include_router(alerts.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": settings.app_name,
            "version": settings.version,
            "docs": "/docs",
            "health": "/api/health",
            "frontend": "http://localhost:5173",
        }
    )


# --------------------------------------------------------------------------
# Optional: serve the built frontend (npm run build) from the same origin.
# Handy for a single-process deployment; in development Vite serves it.
# --------------------------------------------------------------------------
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.is_dir() and os.getenv("SERVE_FRONTEND", "1") == "1":
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = _dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
