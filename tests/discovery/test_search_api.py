from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.api.deps import get_discovery_service, get_search_run_repository
from app.main import app
from app.models import SearchRunStatus, SearchTrigger
from tests.discovery.fakes import FakeSearchRun, FakeSearchRunRepository
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


class StubDiscoveryService:
    def __init__(self, runs: FakeSearchRunRepository) -> None:
        self._runs = runs

    async def run_search(self, *, user_id, query, trigger=SearchTrigger.MANUAL):
        run = await self._runs.create(
            user_id=user_id,
            trigger=trigger,
            query=query.model_dump(mode="json"),
            sources_attempted=["remoteok"],
        )
        return await self._runs.finish(
            run.id,
            status=SearchRunStatus.COMPLETED,
            sources_succeeded=["remoteok"],
            sources_failed=[],
            jobs_found=3,
            jobs_new=2,
            jobs_duplicate=1,
            error_summary=None,
        )


@pytest.fixture
def search_overrides():
    runs = FakeSearchRunRepository()
    app.dependency_overrides[get_search_run_repository] = lambda: runs
    app.dependency_overrides[get_discovery_service] = lambda: StubDiscoveryService(runs)
    yield runs
    app.dependency_overrides.pop(get_search_run_repository, None)
    app.dependency_overrides.pop(get_discovery_service, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_search_requires_auth(auth_client: AuthFixture, search_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.post("/api/v1/search", json={})).status_code == 401
    assert (await client.get("/api/v1/search-runs")).status_code == 401
    assert (await client.get("/api/v1/search-runs/x")).status_code == 401


async def test_post_search_returns_run(auth_client: AuthFixture, search_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.post(
        "/api/v1/search", json={"keywords": ["python"]}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["jobsFound"] == 3 and body["jobsNew"] == 2 and body["jobsDuplicate"] == 1
    assert body["query"] == {
        "keywords": ["python"],
        "targetRoles": [],
        "locations": [],
        "remote": None,
        "experience": None,
        "salary": None,
        "datePosted": None,
        "companies": [],
        "sources": None,
        "limitPerSource": None,
    }


async def test_list_runs_visibility_and_pagination(
    auth_client: AuthFixture, search_overrides
) -> None:
    client, _, _ = auth_client
    runs: FakeSearchRunRepository = search_overrides
    headers = await _login(client)

    # Seed: one own run (via API), one global run, one foreign run.
    await client.post("/api/v1/search", json={}, headers=headers)
    runs.runs["global"] = FakeSearchRun(
        id="global",
        userId=None,
        trigger=SearchTrigger.SCHEDULED,
        status=SearchRunStatus.COMPLETED,
        # The scheduled run's query is the union of every user's targets.
        query={"targetRoles": ["ceo of someone else"], "locations": ["their city"]},
        startedAt=datetime.now(UTC),
    )
    runs.runs["foreign"] = FakeSearchRun(
        id="foreign",
        userId="someone-else",
        trigger=SearchTrigger.MANUAL,
        status=SearchRunStatus.COMPLETED,
        query=None,
        startedAt=datetime.now(UTC),
    )

    response = await client.get("/api/v1/search-runs?limit=10", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2  # own + global, never foreign
    ids = {item["id"] for item in body["items"]}
    assert "global" in ids and "foreign" not in ids
    # Global runs are visible, but their aggregated query is nobody's to read.
    global_run = next(item for item in body["items"] if item["id"] == "global")
    assert global_run["query"] is None
    assert "someone else" not in response.text


async def test_get_run_scoping(auth_client: AuthFixture, search_overrides) -> None:
    client, _, _ = auth_client
    runs: FakeSearchRunRepository = search_overrides
    headers = await _login(client)

    created = await client.post("/api/v1/search", json={}, headers=headers)
    own_id = created.json()["id"]
    runs.runs["foreign"] = FakeSearchRun(
        id="foreign",
        userId="someone-else",
        trigger=SearchTrigger.MANUAL,
        status=SearchRunStatus.COMPLETED,
        query=None,
        startedAt=datetime.now(UTC),
    )
    runs.runs["global"] = FakeSearchRun(
        id="global",
        userId=None,
        trigger=SearchTrigger.SCHEDULED,
        status=SearchRunStatus.COMPLETED,
        query=None,
        startedAt=datetime.now(UTC),
    )

    assert (await client.get(f"/api/v1/search-runs/{own_id}", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/search-runs/global", headers=headers)).status_code == 200
    foreign = await client.get("/api/v1/search-runs/foreign", headers=headers)
    assert foreign.status_code == 404  # existence not leaked
    assert (
        await client.get("/api/v1/search-runs/missing", headers=headers)
    ).status_code == 404


async def test_search_rate_limited(auth_client: AuthFixture, search_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    last = None
    for _ in range(6):  # search budget is 5/minute
        last = await client.post("/api/v1/search", json={}, headers=headers)
    assert last is not None and last.status_code == 429
