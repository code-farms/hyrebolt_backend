import pytest
from httpx import AsyncClient

from app.api.deps import get_analytics_repository
from app.main import app
from tests.analytics.fakes import FakeAnalyticsRepository
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


@pytest.fixture
def analytics_repo() -> FakeAnalyticsRepository:
    repo = FakeAnalyticsRepository()
    app.dependency_overrides[get_analytics_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_analytics_repository, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_overview_returns_every_panel_for_the_requested_range(
    auth_client: AuthFixture, analytics_repo: FakeAnalyticsRepository
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/analytics/overview?range=7", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "range",
        "since",
        "until",
        "timezone",
        "relevantMinScore",
        "discovery",
        "applications",
        "sources",
        "roles",
        "companies",
        "timeseries",
    }
    assert body["range"] == 7
    assert body["discovery"] == {
        "jobsDiscovered": 40,
        "jobsDeduplicated": 12,
        "jobsAnalyzed": 30,
        "jobsMatched": 10,
        "analyzedRate": 75.0,
        "matchedRate": 25.0,
    }
    assert body["applications"]["saved"] == 8 and body["applications"]["interviewRate"] == 33.3
    assert [s["name"] for s in body["sources"]] == ["remoteok", "linkedin"]
    assert [r["family"] for r in body["roles"]] == ["backend", "frontend", "other"]
    assert body["companies"][1] == {
        "companyId": None,
        "companyName": "Globex",
        "jobsFound": 2,
        "relevantJobs": 1,
        "saved": 1,
        "applied": 0,
        "interviews": 0,
    }
    assert len(body["timeseries"]) == 7
    assert set(body["timeseries"][0]) == {"date", "jobsDiscovered", "jobsMatched", "applied", "interviews"}
    # Only aggregates and labels leave the API — no ids of jobs, no recruiter data.
    assert "recruiterEmail" not in response.text and "notes" not in response.text
    # The user id from the JWT is what scopes every user-level query.
    user_ids = {args[0] for name, args in analytics_repo.calls if name != "deduplicated_count"}
    assert len(user_ids) == 1


async def test_overview_defaults_to_thirty_days(
    auth_client: AuthFixture, analytics_repo: FakeAnalyticsRepository
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/analytics/overview", headers=headers)

    assert response.status_code == 200
    assert response.json()["range"] == 30
    assert len(response.json()["timeseries"]) == 30


async def test_overview_rejects_unsupported_range(
    auth_client: AuthFixture, analytics_repo: FakeAnalyticsRepository
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/analytics/overview?range=14", headers=headers)

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_input"
    assert analytics_repo.calls == []


async def test_auth_required(auth_client: AuthFixture, analytics_repo: FakeAnalyticsRepository) -> None:
    client, _, _ = auth_client

    response = await client.get("/api/v1/analytics/overview")

    assert response.status_code == 401
