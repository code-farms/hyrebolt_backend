"""Shared outbound httpx client (one connection pool for all connectors),
mirroring the redis client lifecycle: lazy singleton, closed on shutdown."""

import httpx

_http_client: httpx.AsyncClient | None = None


def get_shared_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
