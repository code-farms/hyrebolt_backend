import pytest
from httpx import AsyncClient

from app.api.deps import get_application_repository, get_job_repository
from app.main import app
from tests.applications.fakes import FakeApplicationRepository
from tests.discovery.test_jobs_api import make_job_row
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


class FakeJobsRepo:
    def __init__(self, ids: list[str]) -> None:
        self.rows = {job_id: make_job_row(job_id) for job_id in ids}

    async def get_by_id(self, job_id: str):
        return self.rows.get(job_id)


@pytest.fixture
def app_overrides():
    repo = FakeApplicationRepository()
    app.dependency_overrides[get_application_repository] = lambda: repo
    app.dependency_overrides[get_job_repository] = lambda: FakeJobsRepo(["j1", "j2"])
    yield repo
    app.dependency_overrides.pop(get_application_repository, None)
    app.dependency_overrides.pop(get_job_repository, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_auth_required(auth_client: AuthFixture, app_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.post("/api/v1/applications", json={"jobId": "j1"})).status_code == 401
    assert (await client.get("/api/v1/applications")).status_code == 401
    assert (await client.get("/api/v1/applications/stats")).status_code == 401


async def test_track_list_and_detail(auth_client: AuthFixture, app_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    created = await client.post(
        "/api/v1/applications", json={"jobId": "j1"}, headers=headers
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "SAVED"
    assert body["job"]["id"] == "j1"
    assert [e["title"] for e in body["events"]] == ["Saved"]

    duplicate = await client.post(
        "/api/v1/applications", json={"jobId": "j1"}, headers=headers
    )
    assert duplicate.json()["id"] == body["id"]  # idempotent

    listing = await client.get("/api/v1/applications", headers=headers)
    assert listing.json()["total"] == 1

    detail = await client.get(f"/api/v1/applications/{body['id']}", headers=headers)
    assert detail.status_code == 200

    unknown_job = await client.post(
        "/api/v1/applications", json={"jobId": "nope"}, headers=headers
    )
    assert unknown_job.status_code == 404


async def test_status_flow_and_filter(auth_client: AuthFixture, app_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)
    app_id = (
        await client.post("/api/v1/applications", json={"jobId": "j1"}, headers=headers)
    ).json()["id"]

    moved = await client.post(
        f"/api/v1/applications/{app_id}/status",
        json={"status": "APPLIED", "note": "sent CV"},
        headers=headers,
    )
    assert moved.status_code == 200
    assert moved.json()["status"] == "APPLIED"
    assert moved.json()["appliedAt"] is not None
    assert moved.json()["events"][-1]["title"] == "Moved to Applied"

    filtered = await client.get("/api/v1/applications?status=APPLIED", headers=headers)
    assert filtered.json()["total"] == 1
    empty = await client.get("/api/v1/applications?status=OFFER", headers=headers)
    assert empty.json()["total"] == 0

    invalid = await client.post(
        f"/api/v1/applications/{app_id}/status", json={"status": "GHOSTED"}, headers=headers
    )
    assert invalid.status_code == 422


async def test_details_events_and_stats(auth_client: AuthFixture, app_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)
    app_id = (
        await client.post("/api/v1/applications", json={"jobId": "j1"}, headers=headers)
    ).json()["id"]

    patched = await client.patch(
        f"/api/v1/applications/{app_id}",
        json={"recruiterName": "Priya", "notes": "intro call done"},
        headers=headers,
    )
    assert patched.json()["recruiterName"] == "Priya"

    event = await client.post(
        f"/api/v1/applications/{app_id}/events",
        json={"title": "Round 1 interview", "notes": "DSA"},
        headers=headers,
    )
    assert event.json()["events"][-1]["title"] == "Round 1 interview"

    stats = await client.get("/api/v1/applications/stats", headers=headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] == 1
    assert body["byStatus"]["SAVED"] == 1

    missing = await client.patch(
        "/api/v1/applications/missing", json={"notes": "x"}, headers=headers
    )
    assert missing.status_code == 404
