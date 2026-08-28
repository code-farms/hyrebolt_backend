"""Phase 18 production-hardening regressions: security headers, body cap,
docs gating, settings validation, URL/scheme allowlists, archive-bomb guard,
rate-limiter failure mode and error-response redaction."""

import io
import zipfile
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from redis.exceptions import RedisError

import app.main as main_module
from app.api.deps import get_prisma, get_redis
from app.core.config import Settings
from app.core.exceptions import InvalidInputError
from app.main import app
from app.services.health_service import HealthService
from app.services.resume_text_extractor import check_docx_archive
from app.sources.boards import board_from_careers_url
from app.utils.normalization import canonicalize_url, is_web_url
from tests.fakes import FakeRedis
from tests.test_health import _FakePrisma, _FakeRedis

BASE_ENV = {
    "database_url": "postgresql://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
}
STRONG_SECRET = "f3c9a1b7e5d24c8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f"


# ── settings ────────────────────────────────────────────────────────────────


def test_jwt_secret_must_be_long_enough() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(**BASE_ENV, jwt_secret="short")
    assert Settings(**BASE_ENV, jwt_secret=STRONG_SECRET).jwt_secret == STRONG_SECRET


def test_production_rejects_placeholder_secret_and_plain_http_origins() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(
            **BASE_ENV,
            environment="production",
            jwt_secret="change-me-generate-a-long-random-string-0123456789",
            cors_origins=["https://app.example.com"],
        )
    with pytest.raises(ValidationError, match="https://"):
        Settings(
            **BASE_ENV,
            environment="production",
            jwt_secret=STRONG_SECRET,
            cors_origins=["http://app.example.com"],
        )
    ok = Settings(
        **BASE_ENV,
        environment="production",
        jwt_secret=STRONG_SECRET,
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    assert ok.is_production and len(ok.cors_origins) == 2


def test_cors_wildcard_is_refused_even_in_development() -> None:
    with pytest.raises(ValidationError, match="explicit origins"):
        Settings(**BASE_ENV, jwt_secret=STRONG_SECRET, cors_origins="*")
    with pytest.raises(ValidationError, match="explicit origins"):
        Settings(**BASE_ENV, jwt_secret=STRONG_SECRET, cors_origins=["http://localhost:5173", "*"])


def test_jwt_algorithm_is_restricted_to_hmac() -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE_ENV, jwt_secret=STRONG_SECRET, jwt_algorithm="none")


# ── app-level middleware ────────────────────────────────────────────────────


async def test_every_response_carries_security_headers(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert response.headers["cache-control"] == "no-store"
    assert "permissions-policy" in response.headers
    # HSTS only makes sense over TLS in production.
    assert "strict-transport-security" not in response.headers


async def test_oversized_json_body_is_rejected_before_parsing(client: AsyncClient) -> None:
    huge = b'{"email": "' + b"a" * (2 * 1024 * 1024) + b'"}'

    response = await client.post(
        "/api/v1/auth/login", content=huge, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "payload_too_large"
    # Rejected below the route, yet still stamped by the outer layers.
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_interactive_docs_are_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    assert app.docs_url == "/docs" and app.openapi_url == "/openapi.json"

    production = Settings(
        **BASE_ENV,
        environment="production",
        jwt_secret=STRONG_SECRET,
        cors_origins=["https://app.example.com"],
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: production)

    hardened = main_module.create_app()

    assert hardened.docs_url is None
    assert hardened.redoc_url is None
    assert hardened.openapi_url is None


async def test_validation_errors_do_not_echo_the_submitted_input(
    auth_client: tuple[AsyncClient, object, object],
) -> None:
    client, _, _ = auth_client  # in-memory Redis for the register rate limiter
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "hunter2-super-secret", "name": "x"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "validation_error"
    assert body["message"], "expected at least one error entry"
    for error in body["message"]:
        assert "input" not in error
    assert "hunter2-super-secret" not in response.text


# ── rate limiter failure mode ───────────────────────────────────────────────


class _BrokenRedis(FakeRedis):
    async def incr(self, key: str) -> int:
        raise RedisError("connection refused")


@pytest.fixture
def broken_redis() -> Iterator[None]:
    app.dependency_overrides[get_redis] = lambda: _BrokenRedis()
    yield
    app.dependency_overrides.pop(get_redis, None)


async def test_rate_limiter_fails_closed_with_503_when_redis_is_down(
    client: AsyncClient, broken_redis: None
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "x@y.co", "password": "whatever123"}
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "dependency_unavailable"


# ── health detail redaction ─────────────────────────────────────────────────


async def test_health_hides_driver_errors_when_details_are_not_exposed() -> None:
    service = HealthService(
        prisma=_FakePrisma(ConnectionError("postgresql://user:pw@db:5432 refused")),  # type: ignore[arg-type]
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        expose_details=False,
    )

    result = await service.get_health()

    assert result.status == "degraded"
    postgres = result.components[0]
    assert postgres.status == "error"
    assert postgres.detail == "unreachable"
    assert "pw@db" not in (postgres.detail or "")


async def test_health_keeps_details_in_development(client: AsyncClient) -> None:
    app.dependency_overrides[get_prisma] = lambda: _FakePrisma(ConnectionError("db down"))
    app.dependency_overrides[get_redis] = lambda: _FakeRedis()
    try:
        response = await client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "db down" in response.json()["components"][0]["detail"]


# ── URL / scheme allowlists ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "ftp://x/y"],
)
def test_canonicalize_url_drops_non_web_schemes(url: str) -> None:
    assert canonicalize_url(url) is None
    assert is_web_url(url) is False


def test_is_web_url_accepts_only_absolute_http_urls() -> None:
    assert is_web_url("https://example.com/jobs/1")
    assert is_web_url("HTTP://example.com")
    assert not is_web_url("example.com/jobs")
    assert not is_web_url("")
    assert not is_web_url(None)
    assert canonicalize_url("HTTPS://Example.com/a/?utm_source=x") == "https://example.com/a"


def test_board_token_must_be_a_plain_slug() -> None:
    assert board_from_careers_url("Acme", "https://boards.greenhouse.io/acme") == {
        "company": "Acme",
        "provider": "greenhouse",
        "token": "acme",
    }
    assert board_from_careers_url("Acme", "https://boards.greenhouse.io/../jobs") is None
    assert board_from_careers_url("Acme", "https://jobs.lever.co/acme%2F..%2Fadmin") is None
    assert board_from_careers_url("Acme", "https://jobs.lever.co/" + "a" * 65) is None


# ── archive bomb guard ──────────────────────────────────────────────────────


def _zip_with_document(payload: bytes, *, members: int = 1) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", payload)
        for index in range(members - 1):
            archive.writestr(f"word/media/{index}.bin", b"x")
    return buffer.getvalue()


def test_docx_archive_guard_accepts_a_normal_document() -> None:
    check_docx_archive(_zip_with_document(b"<w:document>hello</w:document>" * 50))


def test_docx_archive_guard_rejects_decompression_bombs_before_inflating() -> None:
    bomb = _zip_with_document(b"\0" * (10 * 1024 * 1024))  # ~10 MB → a few KB compressed
    assert len(bomb) < 100_000

    with pytest.raises(InvalidInputError, match="too large or complex"):
        check_docx_archive(bomb)


def test_docx_archive_guard_rejects_member_floods_and_non_docx_zips() -> None:
    with pytest.raises(InvalidInputError, match="too large or complex"):
        check_docx_archive(_zip_with_document(b"ok", members=2500))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("not-a-docx.txt", b"hi")
    with pytest.raises(InvalidInputError, match="Only PDF and DOCX"):
        check_docx_archive(buffer.getvalue())
