"""Outbound politeness throttle for connectors: a Redis fixed-window counter
per source that WAITS for the next window instead of raising (this protects
the upstream, it isn't an API guard). Redis-backed so multiple workers
(Phase 9) share one budget."""

import asyncio
import time
from collections.abc import Awaitable, Callable

import redis.asyncio as redis

from app.sources.http import Throttle

_WINDOW_SECONDS = 60


def make_source_throttle(
    redis_client: redis.Redis,
    source_name: str,
    per_minute: int | None,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.time,
) -> Throttle | None:
    if per_minute is None or per_minute <= 0:
        return None

    async def throttle() -> None:
        while True:
            now = clock()
            window = int(now // _WINDOW_SECONDS)
            key = f"source_throttle:{source_name}:{window}"
            count = await redis_client.incr(key)
            if count == 1:
                # A little longer than the window so stragglers still expire.
                await redis_client.expire(key, _WINDOW_SECONDS + 30)
            if count <= per_minute:
                return
            await sleep((window + 1) * _WINDOW_SECONDS - now)

    return throttle
