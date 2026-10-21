"""Small async TTL cache with stale-on-error fallback and request coalescing."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    stored_at: float


class TTLCache:
    """In-memory cache. Values expire after ``ttl`` seconds.

    ``get_or_set`` will return an expired (stale) value if the producer raises,
    which keeps the UI usable when an upstream provider is briefly unavailable.

    Concurrent requests for the same key share a single upstream call. Without
    this, a browser that fires two overlapping requests (React StrictMode
    mounts effects twice in development) would make two identical calls to the
    provider, doubling the load and making a transient upstream failure far
    more likely.
    """

    def __init__(self, max_entries: int = 512) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries
        self._inflight: dict[str, asyncio.Task] = {}

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.time():
                return None
            return entry.value

    async def get_stale(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._entries.get(key)
            return entry.value if entry else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            now = time.time()
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries.items(), key=lambda kv: kv[1].stored_at)[0]
                self._entries.pop(oldest, None)
            self._entries[key] = CacheEntry(
                value=value, expires_at=now + ttl, stored_at=now
            )

    async def _produce(
        self,
        key: str,
        ttl: int,
        producer: Callable[[], Awaitable[Any]],
        stale_on_error: bool,
    ) -> tuple[Any, bool]:
        try:
            value = await producer()
        except Exception:
            if stale_on_error:
                stale = await self.get_stale(key)
                if stale is not None:
                    return stale, True
            raise
        await self.set(key, value, ttl)
        return value, False

    def _release(self, key: str, task: asyncio.Task) -> None:
        """Drop a finished task and swallow its exception.

        Retrieving the exception here stops asyncio from logging
        "Task exception was never retrieved"; waiters still receive it.
        """
        if self._inflight.get(key) is task:
            self._inflight.pop(key, None)
        if not task.cancelled():
            task.exception()

    async def get_or_set(
        self,
        key: str,
        ttl: int,
        producer: Callable[[], Awaitable[Any]],
        *,
        stale_on_error: bool = True,
    ) -> tuple[Any, bool]:
        """Return ``(value, is_stale)``.

        ``is_stale`` is True when the cached value had already expired and was
        served because the producer failed.
        """
        cached = await self.get(key)
        if cached is not None:
            return cached, False

        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._produce(key, ttl, producer, stale_on_error)
                )
                self._inflight[key] = task
                task.add_done_callback(lambda t: self._release(key, t))

        # ``shield`` keeps the shared upstream call alive even when one of the
        # waiting requests is cancelled (for example the browser navigated away).
        return await asyncio.shield(task)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()


cache = TTLCache()
