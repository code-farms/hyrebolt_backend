import pytest
from httpx import AsyncClient

from app.api.deps import get_job_analysis_service, get_job_repository
from app.main import app
from tests.ai.fakes import FakeJob
from tests.ai.test_analysis_service import FULL_ANALYSIS, ScriptedProvider, make_service
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


class FakeJobLookupRepo:
    def __init__(self, jobs: list[FakeJob]) -> None:
        self.jobs = {job.id: job for job in jobs}

    async def get_by_id(self, job_id: str):
        return self.jobs.get(job_id)


@pytest.fixture
def analysis_overrides():
    job = FakeJob()
    provider = ScriptedProvider([FULL_ANALYSIS, FULL_ANALYSIS])
    service, analyses, _ = make_service(provider, jobs=[job])
    app.dependency_overrides[get_job_repository] = lambda: FakeJobLookupRepo([job])
    app.dependency_overrides[get_job_analysis_service] = lambda: service
    yield job, provider, analyses
    app.dependency_overrides.pop(get_job_repository, None)
    app.dependency_overrides.pop(get_job_analysis_service, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_analyze_requires_auth(auth_client: AuthFixture, analysis_overrides) -> None:
    client, _, _ = auth_client
    job, _, _ = analysis_overrides
    assert (await client.post(f"/api/v1/jobs/{job.id}/analyze")).status_code == 401


async def test_analyze_unknown_job_404(auth_client: AuthFixture, analysis_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)
    assert (
        await client.post("/api/v1/jobs/missing/analyze", headers=headers)
    ).status_code == 404


async def test_analyze_returns_result_and_caches(
    auth_client: AuthFixture, analysis_overrides
) -> None:
    client, _, _ = auth_client
    job, provider, _ = analysis_overrides
    headers = await _login(client)

    first = await client.post(f"/api/v1/jobs/{job.id}/analyze", headers=headers)
    second = await client.post(f"/api/v1/jobs/{job.id}/analyze", headers=headers)

    assert first.status_code == 200
    body = first.json()
    assert body["jobId"] == job.id
    assert body["promptVersion"]
    assert body["model"] == "scripted"
    assert body["analysis"]["title"] == "Backend Engineer"
    assert body["analysis"]["workMode"] == "HYBRID"
    assert body["analysis"]["salary"] == {"min": 2000000, "max": 3000000, "currency": "INR"}

    assert provider.calls == 1  # second request served from the cache
    assert second.json()["processedAt"] == body["processedAt"]
