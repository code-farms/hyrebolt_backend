from pathlib import Path

import pytest
from httpx import AsyncClient

from app.ai import MockLLMProvider
from app.api.deps import (
    get_job_repository,
    get_resume_analysis_service,
    get_resume_gap_service,
    get_resume_service,
)
from app.core.config import get_settings
from app.main import app
from app.services.job_analysis_service import JobAnalysisService
from app.services.resume_analysis_service import ResumeAnalysisService
from app.services.resume_gap_service import ResumeGapService
from app.services.resume_service import ResumeService
from app.services.resume_storage import ResumeStorage
from tests.ai.fakes import FakeAnalysisRepository, FakeJob, FakeJobsForAnalysis
from tests.fakes import FakeDB, FakeProfileRepository, FakeRedis
from tests.resumes.fakes import (
    RESUME_LINES,
    FakeResumeAnalysisRepository,
    FakeResumeGapRepository,
    FakeResumeRepository,
    FakeSkillNames,
    make_docx,
    make_pdf,
)

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]
BASE = "/api/v1/resumes"


class FakeJobsRepo:
    def __init__(self, jobs: list[FakeJob]) -> None:
        self.rows = {job.id: job for job in jobs}

    async def get_with_listings(self, job_id: str):
        return self.rows.get(job_id)


@pytest.fixture
def resume_overrides(auth_client: AuthFixture, tmp_path: Path):
    _, db, _ = auth_client
    settings = get_settings().model_copy(update={"resume_max_upload_mb": 1})
    profiles = FakeProfileRepository(db)
    analyses = FakeResumeAnalysisRepository()
    resumes = FakeResumeRepository(analyses, profiles)
    storage = ResumeStorage(tmp_path)
    skills = FakeSkillNames(["Python", "Postgres", "Kubernetes"])
    provider = MockLLMProvider()
    job = FakeJob(
        id="j1", title="Platform Engineer", description="Python and Kubernetes; Postgres a plus."
    )
    job_analyses = FakeAnalysisRepository()
    job_lookup = FakeJobsForAnalysis([job])
    job_lookup.analyses = job_analyses
    job_analysis_service = JobAnalysisService(
        provider, job_analyses, job_lookup, settings  # type: ignore[arg-type]
    )

    app.dependency_overrides[get_resume_service] = lambda: ResumeService(
        resumes=resumes, profiles=profiles, storage=storage, settings=settings  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_resume_analysis_service] = lambda: ResumeAnalysisService(
        provider, analyses, skills, settings  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_resume_gap_service] = lambda: ResumeGapService(
        provider=provider,
        gaps=FakeResumeGapRepository(),  # type: ignore[arg-type]
        job_analysis=job_analysis_service,
        profiles=profiles,  # type: ignore[arg-type]
        skills=skills,  # type: ignore[arg-type]
        settings=settings,
    )
    app.dependency_overrides[get_job_repository] = lambda: FakeJobsRepo([job])
    app.dependency_overrides[get_settings] = lambda: settings  # 1 MB upload cap for the router
    yield resumes, tmp_path
    for dep in (
        get_resume_service,
        get_resume_analysis_service,
        get_resume_gap_service,
        get_job_repository,
        get_settings,
    ):
        app.dependency_overrides.pop(dep, None)


async def _login(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    payload = {"email": email, "password": "password123", "name": "Test User"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": payload["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def pdf_upload(name: str = "cv.pdf", lines: list[str] | None = None):
    return {"file": (name, make_pdf(lines or RESUME_LINES), "application/pdf")}


async def test_auth_required(auth_client: AuthFixture, resume_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.get(BASE)).status_code == 401
    assert (await client.post(BASE, files=pdf_upload())).status_code == 401
    assert (await client.get(f"{BASE}/gap/j1")).status_code == 401


async def test_upload_list_detail_analyze_and_download(auth_client: AuthFixture, resume_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    created = await client.post(BASE, files=pdf_upload(), data={"title": "Main CV"}, headers=headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Main CV" and body["isSelected"] is True
    version = body["versions"][0]
    assert version["versionNumber"] == 1 and version["analysis"] is None
    assert "extractedText" not in version  # list shape stays slim

    listed = await client.get(BASE, headers=headers)
    assert listed.json()["total"] == 1 and listed.json()["selectedResumeId"] == body["id"]

    detail = await client.get(f"{BASE}/versions/{version['id']}", headers=headers)
    assert detail.status_code == 200
    assert "PostgreSQL" in detail.json()["extractedText"]

    analyzed = await client.post(f"{BASE}/versions/{version['id']}/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    analysis = analyzed.json()["analysis"]
    assert analysis["promptVersion"] == "resume-v1" and analysis["model"] == "mock"
    # Mock provider extracts nothing; the catalog scan still grounds the skills.
    assert analysis["analysis"]["skills"] == ["Python", "Postgres", "Kubernetes"]

    download = await client.get(f"{BASE}/versions/{version['id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert 'filename="cv.pdf"' in download.headers["content-disposition"]
    assert download.content.startswith(b"%PDF-")

    # A second version of the same resume via DOCX.
    second = await client.post(
        BASE,
        files={"file": ("cv2.docx", make_docx(["Priya Sharma", "Go developer"]), "application/octet-stream")},
        data={"resumeId": body["id"]},
        headers=headers,
    )
    assert second.status_code == 201
    assert [v["versionNumber"] for v in second.json()["versions"]] == [2, 1]


async def test_upload_validation(auth_client: AuthFixture, resume_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    wrong_type = await client.post(BASE, files={"file": ("cv.txt", b"hello", "text/plain")}, headers=headers)
    assert wrong_type.status_code == 422
    assert "PDF and DOCX" in wrong_type.json()["message"]

    too_big = await client.post(
        BASE, files={"file": ("cv.pdf", b"%PDF-" + b"0" * (1024 * 1024 + 10), "application/pdf")}, headers=headers
    )
    assert too_big.status_code == 422
    assert "1 MB" in too_big.json()["message"]

    empty = await client.post(BASE, files={"file": ("cv.pdf", b"", "application/pdf")}, headers=headers)
    assert empty.status_code == 422

    unknown_resume = await client.post(BASE, files=pdf_upload(), data={"resumeId": "nope"}, headers=headers)
    assert unknown_resume.status_code == 404


async def test_gap_select_ownership_and_delete(auth_client: AuthFixture, resume_overrides) -> None:
    client, _, _ = auth_client
    resumes, tmp_path = resume_overrides
    headers = await _login(client)

    no_resume = await client.get(f"{BASE}/gap/j1", headers=headers)
    assert no_resume.status_code == 404
    assert no_resume.json()["message"] == "No resume selected."

    a = (await client.post(BASE, files=pdf_upload("a.pdf"), data={"title": "A"}, headers=headers)).json()
    b = (await client.post(BASE, files=pdf_upload("b.pdf", ["Only Go here"]), data={"title": "B"}, headers=headers)).json()

    gap = await client.get(f"{BASE}/gap/j1", headers=headers)
    assert gap.status_code == 200, gap.text
    result = gap.json()["result"]
    assert gap.json()["resumeId"] == a["id"]  # first upload is the selected one
    assert set(result["matchedSkills"]) == {"Python", "Kubernetes", "Postgres"}
    assert result["aiAvailable"] is True and result["suggestedImprovements"] == []  # mock: nothing grounded

    selected = await client.post(f"{BASE}/{b['id']}/select", headers=headers)
    assert selected.status_code == 200 and selected.json()["isSelected"] is True
    gap_b = await client.get(f"{BASE}/gap/j1", headers=headers)
    assert gap_b.json()["resumeId"] == b["id"]
    assert gap_b.json()["result"]["matchedSkills"] == []

    per_version = await client.get(f"{BASE}/versions/{a['versions'][0]['id']}/gap/j1", headers=headers)
    assert per_version.status_code == 200
    missing_job = await client.get(f"{BASE}/gap/nope", headers=headers)
    assert missing_job.status_code == 404

    other = await _login(client, "other@example.com")
    assert (await client.get(f"{BASE}/{a['id']}", headers=other)).status_code == 404
    assert (await client.post(f"{BASE}/{a['id']}/select", headers=other)).status_code == 404
    assert (await client.get(f"{BASE}/versions/{a['versions'][0]['id']}", headers=other)).status_code == 404
    assert (await client.delete(f"{BASE}/{a['id']}", headers=other)).status_code == 404

    stored = tmp_path / resumes.versions[b["versions"][0]["id"]].storagePath
    assert stored.is_file()
    deleted = await client.delete(f"{BASE}/{b['id']}", headers=headers)
    assert deleted.status_code == 204
    assert not stored.exists()
    assert (await client.get(f"{BASE}/gap/j1", headers=headers)).status_code == 404  # selection cleared
    assert (await client.get(BASE, headers=headers)).json()["total"] == 1
