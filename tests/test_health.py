import asyncio
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.api.deps import get_prisma, get_redis
from app.main import app
from app.services.health_service import WORKER_HEALTH_KEY, HealthService


class _FakePrisma:
    def __init__(self, error: Exception | None = None, *, hang: bool = False) -> None:
        self._error = error
        self._hang = hang

    async def query_raw(self, query: str) -> list[dict[str, object]]:
        if self._hang:
            await asyncio.sleep(60)
        if self._error is not None:
            raise self._error
        return [{"?column?": 1}]


class _FakeRedis:
    def __init__(self, error: Exception | None = None, *, worker_alive: bool = True) -> None:
        self._error = error
        self._worker_alive = worker_alive

    async def ping(self) -> bool:
        if self._error is not None:
            raise self._error
        return True

    async def get(self, key: str) -> str | None:
        if self._error is not None:
            raise self._error
        return "1" if key == WORKER_HEALTH_KEY and self._worker_alive else None


def _override(prisma: _FakePrisma, redis_client: _FakeRedis) -> None:
    app.dependency_overrides[get_prisma] = lambda: prisma
    app.dependency_overrides[get_redis] = lambda: redis_client


@pytest.fixture
def healthy_dependencies() -> Iterator[None]:
    _override(_FakePrisma(), _FakeRedis())
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def failing_database() -> Iterator[None]:
    _override(_FakePrisma(ConnectionError("db down")), _FakeRedis())
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def failing_redis() -> Iterator[None]:
    _override(_FakePrisma(), _FakeRedis(ConnectionError("redis down")))
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def missing_worker() -> Iterator[None]:
    _override(_FakePrisma(), _FakeRedis(worker_alive=False))
    yield
    app.dependency_overrides.clear()


async def test_health_live_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_reports_all_components_ok(
    client: AsyncClient, healthy_dependencies: None
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"] == [
        {"name": "postgres", "status": "ok", "detail": None},
        {"name": "redis", "status": "ok", "detail": None},
        {"name": "worker", "status": "ok", "detail": None},
    ]


async def test_health_returns_503_with_breakdown_when_database_is_down(
    client: AsyncClient, failing_database: None
) -> None:
    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    postgres, redis_component, worker = body["components"]
    assert postgres["name"] == "postgres"
    assert postgres["status"] == "error"
    assert "db down" in postgres["detail"]
    assert redis_component == {"name": "redis", "status": "ok", "detail": None}
    assert worker["status"] == "ok"


async def test_health_reports_redis_failure_for_redis_and_worker(
    client: AsyncClient, failing_redis: None
) -> None:
    response = await client.get("/health")

    assert response.status_code == 503
    postgres, redis_component, worker = response.json()["components"]
    assert postgres["status"] == "ok"
    assert redis_component["status"] == "error" and "redis down" in redis_component["detail"]
    # The heartbeat lives in Redis, so the worker cannot be confirmed either.
    assert worker["status"] == "error"


async def test_missing_worker_heartbeat_degrades_health_but_not_readiness(
    client: AsyncClient, missing_worker: None
) -> None:
    health = await client.get("/health")
    ready = await client.get("/ready")

    assert health.status_code == 503
    worker = health.json()["components"][2]
    assert worker == {"name": "worker", "status": "error", "detail": "no worker heartbeat"}

    # The API can still serve requests without a worker.
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"
    assert [c["name"] for c in ready.json()["components"]] == ["postgres", "redis"]


async def test_ready_returns_503_when_a_hard_dependency_is_down(
    client: AsyncClient, failing_database: None
) -> None:
    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


async def test_probes_time_out_instead_of_hanging() -> None:
    service = HealthService(
        prisma=_FakePrisma(hang=True),  # type: ignore[arg-type]
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        probe_timeout=0.05,
    )

    result = await asyncio.wait_for(service.get_readiness(), timeout=2)

    assert result.status == "degraded"
    assert result.components[0] == {
        "name": "postgres",
        "status": "error",
        "detail": "timed out",
    } or result.components[0].detail == "timed out"
