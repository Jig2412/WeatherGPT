"""AI weather assistant endpoint."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request

from ..config import get_settings
from ..errors import RateLimitError
from ..schemas import ChatRequest, ChatResponse
from ..services import ai

router = APIRouter(prefix="/api", tags=["ai"])

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request) -> None:
    settings = get_settings()
    limit = settings.chat_rate_limit_per_minute
    key = _client_key(request)
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = int(60 - (now - bucket[0])) + 1
        raise RateLimitError(
            f"Too many AI requests. Limit is {limit} per minute; try again in ~{retry_after}s.",
            provider="Anthropic",
            retry_after=retry_after,
        )
    bucket.append(now)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    """Talk to Claude about the weather. Claude retrieves real data via tools."""
    _enforce_rate_limit(request)
    return await ai.run_chat(
        [m.model_dump() for m in payload.messages],
        location=payload.location,
        units=payload.units,
    )
