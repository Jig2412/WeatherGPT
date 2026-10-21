"""Shared HTTP helpers for talking to third-party weather providers."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import get_settings
from ..errors import UpstreamError


def build_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=8.0),
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        },
        follow_redirects=True,
    )


def _describe(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("reason", "message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET a JSON document, converting transport/HTTP problems into UpstreamError."""
    try:
        response = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpstreamError(
            provider,
            f"{provider} timed out while answering the request.",
            status_code=504,
            code="upstream_timeout",
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(
            provider,
            f"Could not reach {provider}: {exc.__class__.__name__}.",
            status_code=502,
            code="upstream_unreachable",
        ) from exc

    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After") or 60)
        detail = _describe(_safe_json(response)) or "rate limit reached"
        raise UpstreamError(
            provider,
            f"{provider} rate limit reached ({detail}). Retrying in ~{retry_after}s.",
            status_code=429,
            code="rate_limited",
            retry_after=retry_after,
        )

    if response.status_code >= 400:
        detail = _describe(_safe_json(response))
        raise UpstreamError(
            provider,
            f"{provider} returned HTTP {response.status_code}. {detail}".strip(),
            status_code=502,
            code="upstream_http_error",
        )

    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise UpstreamError(
            provider,
            f"{provider} returned a response that is not valid JSON.",
            status_code=502,
            code="invalid_response",
        ) from exc


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None
