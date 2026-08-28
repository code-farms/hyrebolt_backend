"""Production-hardening ASGI middleware (Phase 18).

Pure ASGI (no BaseHTTPMiddleware) so streaming responses and the request
body are never buffered twice.
"""

import json
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import structlog
from starlette.datastructures import Headers

from app.core.logging import get_logger

logger = get_logger("app.http")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# A JSON API never renders HTML, so the strictest CSP is safe and blocks any
# attempt to load a response (e.g. a resume download) as an active document.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}
HSTS_HEADER = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self._app = app
        self._hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = dict(SECURITY_HEADERS)
                if self._hsts:
                    extra["Strict-Transport-Security"] = HSTS_HEADER
                for name, value in extra.items():
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_with_headers)


REQUEST_ID_HEADER = "x-request-id"
# Probes are noisy and carry no user intent; they stay out of the access log.
_QUIET_PATHS = frozenset({"/health", "/health/live", "/ready"})


class RequestLoggingMiddleware:
    """One structured `http_request` event per request (method, path, status,
    duration) with a request id bound into structlog's contextvars, so every
    log line emitted while handling the request — including
    `unhandled_exception` — carries the same id. The id is echoed back in
    X-Request-ID so a client report can be matched to the log."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = incoming[:64] if incoming and incoming.isprintable() else uuid.uuid4().hex
        path = scope.get("path", "")
        method = scope.get("method", "")
        status_code = 0
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if path not in _QUIET_PATHS:
                log = logger.warning if status_code >= 500 else logger.info
                log(
                    "http_request",
                    method=method,
                    path=path,
                    status=status_code,
                    duration_ms=duration_ms,
                )
            structlog.contextvars.clear_contextvars()


class BodyTooLargeError(Exception):
    """Raised from the wrapped receive() once a chunked body passes the cap."""


class BodySizeLimitMiddleware:
    """Rejects request bodies above ``max_bytes`` with 413. Multipart uploads
    are exempt: the resume route streams them and enforces its own cap."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("content-type", "").lower().startswith("multipart/form-data"):
            await self._app(scope, receive, send)
            return

        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await self._reject(send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise BodyTooLargeError
            return message

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            if not response_started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            {
                "error_code": "payload_too_large",
                "message": f"Request body exceeds {self._max_bytes} bytes.",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
