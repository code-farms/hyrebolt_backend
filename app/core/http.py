"""Shared outbound httpx client (one connection pool for all connectors),
mirroring the redis client lifecycle: lazy singleton, closed on shutdown.

Defaults are deliberately conservative so a caller that forgets a per-request
timeout is still bounded, and a redirect chain from a pinned host cannot walk
the crawler somewhere else."""

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_LIMITS = httpx.Limits(max_connections=50, max_keepalive_connections=20)
MAX_REDIRECTS = 3

_http_client: httpx.AsyncClient | None = None


def build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT, limits=DEFAULT_LIMITS, max_redirects=MAX_REDIRECTS
    )


def get_shared_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = build_http_client()
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
