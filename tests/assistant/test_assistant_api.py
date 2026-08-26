import pytest
from httpx import AsyncClient

from app.ai import MockLLMProvider
from app.api.deps import get_application_assistant_service, get_job_repository
from app.core.config import get_settings
from app.main import app
from app.services.application_assistant_service import ApplicationAssistantService
from tests.assistant.fakes import (
    FakeDraftRepository,
    FakeResumesForAssistant,
    make_job,
    make_version,
)
from tests.companies.fakes import FakeCompanyRepository
from tests.fakes import FakeDB, FakeProfileRepository, FakeRedis
from tests.resumes.fakes import FakeSkillNames

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]
BASE = "/api/v1/assistant"


class FakeJobsRepo:
    def __init__(self, jobs) -> None:
        self.rows = {job.id: job for job in jobs}

    async def get_with_listings(self, job_id: str):
        return self.rows.get(job_id)


@pytest.fixture
def assistant_overrides(auth_client: AuthFixture):
    _, db, _ = auth_client
    service = ApplicationAssistantService(
        provider=MockLLMProvider(),
        drafts=FakeDraftRepository(),  # type: ignore[arg-type]
        profiles=FakeProfileRepository(db),  # type: ignore[arg-type]
        companies=FakeCompanyRepository(),  # type: ignore[arg-type]
        resumes=FakeResumesForAssistant(make_version()),  # type: ignore[arg-type]
        skills=FakeSkillNames(["Python", "Kubernetes"]),  # type: ignore[arg-type]
        settings=get_settings(),
    )
    app.dependency_overrides[get_application_assistant_service] = lambda: service
    app.dependency_overrides[get_job_repository] = lambda: FakeJobsRepo([make_job()])
    yield service
    app.dependency_overrides.pop(get_application_assistant_service, None)
    app.dependency_overrides.pop(get_job_repository, None)


async def _login(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    payload = {"email": email, "password": "password123", "name": "Test User"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": payload["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_auth_required(auth_client: AuthFixture, assistant_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.get(f"{BASE}/j1")).status_code == 401
    assert (await client.post(f"{BASE}/j1/generate", json={})).status_code == 401
    assert (await client.put(f"{BASE}/j1/drafts/COVER_LETTER", json={"content": "x"})).status_code == 401


async def test_generate_save_and_regenerate_flow(auth_client: AuthFixture, assistant_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    empty = await client.get(f"{BASE}/j1", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["selectedResumeVersionId"] == "v1"
    assert all(value is None for value in empty.json()["drafts"].values())

    generated = await client.post(f"{BASE}/j1/generate", json={}, headers=headers)
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["failed"] == []
    assert set(body["drafts"]) == {"COVER_LETTER", "RECRUITER_MESSAGE", "RESUME_TAILORING", "APPLICATION_NOTES"}
    cover = body["drafts"]["COVER_LETTER"]
    assert "Platform Engineer at Globex" in cover["content"]  # mock echoes the job
    assert cover["promptVersion"] == "assistant/cover-letter-v1"
    assert cover["resumeVersionId"] == "v1" and cover["model"] == "mock"
    assert cover["edited"] is False and cover["generatedAt"] is not None

    saved = await client.put(
        f"{BASE}/j1/drafts/COVER_LETTER", json={"content": "Edited by me."}, headers=headers
    )
    assert saved.status_code == 200
    assert saved.json()["content"] == "Edited by me." and saved.json()["edited"] is True
    assert saved.json()["generatedContent"] == cover["content"]

    regenerated = await client.post(
        f"{BASE}/j1/generate", json={"kinds": ["COVER_LETTER"], "force": True}, headers=headers
    )
    assert regenerated.json()["drafts"]["COVER_LETTER"]["edited"] is False

    assert (await client.put(f"{BASE}/j1/drafts/COVER_LETTER", json={"content": ""}, headers=headers)).status_code == 422
    assert (await client.put(f"{BASE}/j1/drafts/TWEET", json={"content": "x"}, headers=headers)).status_code == 422
    assert (await client.get(f"{BASE}/nope", headers=headers)).status_code == 404
    assert (await client.post(f"{BASE}/j1/generate", json={"kinds": ["NOPE"]}, headers=headers)).status_code == 422

    other = await _login(client, "other@example.com")
    assert all(v is None for v in (await client.get(f"{BASE}/j1", headers=other)).json()["drafts"].values())
