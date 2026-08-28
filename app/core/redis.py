"""Process-wide Redis client (rate limits, refresh tokens, throttles, worker
heartbeat). Socket timeouts are mandatory: without them a blackholed Redis
hangs every health probe and the discovery throttle forever."""

import redis.asyncio as redis

from app.core.config import Settings

SOCKET_TIMEOUT_SECONDS = 5.0
HEALTH_CHECK_INTERVAL_SECONDS = 30
MAX_CONNECTIONS = 50

_redis_client: redis.Redis | None = None


def build_redis_client(redis_url: str) -> redis.Redis:
    return redis.from_url(
        redis_url,
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
        retry_on_timeout=True,
        max_connections=MAX_CONNECTIONS,
    )


def get_redis_client(settings: Settings) -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = build_redis_client(settings.redis_url)
    return _redis_client


async def close_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
