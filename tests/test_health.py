from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.api.deps import get_prisma, get_redis
from app.main import app


class _FakeSystemStatus:
    def __init__(self, error: Exception | None) -> None:
        self._error = error

    async def count(self) -> int:
        if self._error is not None:
            raise self._error
        return 0


class _FakePrisma:
    def __init__(self, error: Exception | None = None) -> None:
        self.systemstatus = _FakeSystemStatus(error)


class _FakeRedis:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def ping(self) -> bool:
        if self._error is not None:
            raise self._error
        return True


@pytest.fixture
def healthy_dependencies() -> Iterator[None]:
    app.dependency_overrides[get_prisma] = lambda: _FakePrisma()
    app.dependency_overrides[get_redis] = lambda: _FakeRedis()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def failing_database() -> Iterator[None]:
    app.dependency_overrides[get_prisma] = lambda: _FakePrisma(ConnectionError("db down"))
    app.dependency_overrides[get_redis] = lambda: _FakeRedis()
    yield
    app.dependency_overrides.clear()


async def test_health_live_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_readiness_reports_all_components_ok(
    client: AsyncClient, healthy_dependencies: None
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"] == [
        {"name": "postgres", "status": "ok", "detail": None},
        {"name": "redis", "status": "ok", "detail": None},
    ]


async def test_health_readiness_returns_503_with_breakdown_when_degraded(
    client: AsyncClient, failing_database: None
) -> None:
    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    postgres, redis_component = body["components"]
    assert postgres["name"] == "postgres"
    assert postgres["status"] == "error"
    assert "db down" in postgres["detail"]
    assert redis_component == {"name": "redis", "status": "ok", "detail": None}
