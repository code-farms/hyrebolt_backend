from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.api.deps import get_agent_status_service
from app.core.config import get_settings
from app.main import app
from app.models import SearchRunStatus, SearchTrigger
from app.services.agent_status_service import AgentStatusService
from tests.discovery.fakes import FakeSearchRun
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


class FakeRunsRepo:
    def __init__(self, run: FakeSearchRun | None) -> None:
        self.run = run

    async def latest_by_trigger(self, trigger: SearchTrigger):
        return self.run


class FakeMatchesRepo:
    async def count_updated_since(self, since) -> int:
        return 7


class FakeNotificationsRepo:
    async def count_since(self, since) -> int:
        return 2


def make_status_service(run: FakeSearchRun | None, redis: FakeRedis) -> AgentStatusService:
    return AgentStatusService(
        search_runs=FakeRunsRepo(run),  # type: ignore[arg-type]
        matches=FakeMatchesRepo(),  # type: ignore[arg-type]
        notifications=FakeNotificationsRepo(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        settings=get_settings(),
    )


@pytest.fixture
def status_overrides():
    run = FakeSearchRun(
        id="run-1",
        userId=None,
        trigger=SearchTrigger.SCHEDULED,
        status=SearchRunStatus.PARTIAL,
        query={"targetRoles": ["Backend Engineer"]},
        startedAt=datetime.now(UTC),
        sourcesFailed=["linkedin"],
        errorSummary="linkedin: disabled",
        jobsFound=10,
        jobsNew=3,
        jobsDuplicate=7,
    )
    redis = FakeRedis()
    app.dependency_overrides[get_agent_status_service] = lambda: make_status_service(run, redis)
    yield run, redis
    app.dependency_overrides.pop(get_agent_status_service, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_status_requires_auth(auth_client: AuthFixture, status_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.get("/api/v1/agent/status")).status_code == 401


async def test_status_shape(auth_client: AuthFixture, status_overrides) -> None:
    client, _, _ = auth_client
    _, redis = status_overrides
    redis.store["arq:queue:health-check"] = "ok"
    headers = await _login(client)

    response = await client.get("/api/v1/agent/status", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["lastRun"]["status"] == "PARTIAL"
    assert body["lastRun"]["jobsNew"] == 3
    assert body["failures"] == ["linkedin"]
    assert body["errorSummary"] == "linkedin: disabled"
    assert body["jobsMatchedLast24h"] == 7
    assert body["notificationsCreatedLast24h"] == 2
    assert body["workerHealthy"] is True
    assert body["nextRunAt"]
    assert body["schedule"] == {
        "dailySearchTime": get_settings().daily_search_time,
        "timezone": get_settings().timezone,
    }


async def test_status_worker_unhealthy_and_no_runs(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    redis = FakeRedis()  # no health key
    app.dependency_overrides[get_agent_status_service] = lambda: make_status_service(None, redis)
    try:
        headers = await _login(client)
        response = await client.get("/api/v1/agent/status", headers=headers)
    finally:
        app.dependency_overrides.pop(get_agent_status_service, None)

    body = response.json()
    assert body["lastRun"] is None
    assert body["failures"] == []
    assert body["workerHealthy"] is False
