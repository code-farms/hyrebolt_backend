import pytest
from httpx import AsyncClient

from app.api.deps import get_job_analysis_service, get_job_repository
from app.main import app
from app.schemas.analysis import JOB_ANALYSIS_PROMPT_VERSION
from app.schemas.job import _current_analysis_out
from tests.ai.fakes import FakeAnalysisRepository, FakeJob
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
    assert (await client.post("/api/v1/jobs/missing/analyze", headers=headers)).status_code == 404


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


async def test_job_payload_hides_stale_analysis() -> None:
    """A row from an older prompt version (or the mock provider before a real
    key was configured) must not render as an empty analysis card: the client
    sees null and requests a fresh analysis."""
    from datetime import UTC, datetime

    repo = FakeAnalysisRepository()
    common = {
        "analysis": FULL_ANALYSIS,
        "confidence": 0.9,
        "model": "scripted",
        "input_tokens": 1,
        "output_tokens": 1,
        "processed_at": datetime.now(UTC),
    }
    stale = await repo.upsert_for_job("stale", prompt_version="stale-mock", **common)
    current = await repo.upsert_for_job(
        "current", prompt_version=JOB_ANALYSIS_PROMPT_VERSION, **common
    )

    assert _current_analysis_out(None) is None
    assert _current_analysis_out(stale) is None
    out = _current_analysis_out(current)
    assert out is not None and out.analysis.title == "Backend Engineer"
