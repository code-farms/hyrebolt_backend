"""Single choke point for all outbound connector HTTP: honest User-Agent,
per-source timeout, optional throttle hook (Phase 5 rate limiting), and
translation of transport failures into the SourceError taxonomy so connectors
never handle httpx semantics themselves."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.sources.exceptions import (
    SourceAuthRequiredError,
    SourceRateLimitedError,
    SourceUnavailableError,
)

# Awaited before every request when set; Phase 5 plugs a Redis limiter in here.
Throttle = Callable[[], Awaitable[None]]

USER_AGENT = "job-agent/0.1 (personal job search agent; contact: see repository)"


class SourceHTTPClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        source_name: str,
        timeout_seconds: float,
        throttle: Throttle | None = None,
    ) -> None:
        self._client = client
        self._source_name = source_name
        self._timeout = timeout_seconds
        self._throttle = throttle

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self._get(url, params=params, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceUnavailableError(
                self._source_name, f"non-JSON response from {url}"
            ) from exc

    async def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        response = await self._get(url, params=params, headers=headers)
        return response.text

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        if self._throttle is not None:
            await self._throttle()
        try:
            response = await self._client.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
                timeout=self._timeout,
                follow_redirects=True,
            )
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError(self._source_name, f"timeout calling {url}") from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(
                self._source_name, f"network error calling {url}: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise SourceAuthRequiredError(
                self._source_name, f"upstream rejected the request ({response.status_code})"
            )
        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after = (
                float(retry_after_header)
                if retry_after_header and retry_after_header.replace(".", "", 1).isdigit()
                else None
            )
            raise SourceRateLimitedError(
                self._source_name, "upstream rate limit hit", retry_after=retry_after
            )
        if response.status_code >= 400:
            raise SourceUnavailableError(
                self._source_name, f"upstream returned {response.status_code} for {url}"
            )
        return response
