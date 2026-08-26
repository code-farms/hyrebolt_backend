from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.exceptions import LLMResponseError, LLMUnavailableError
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.services.resume_analysis_service import (
    RESUME_PROMPT_VERSION,
    ResumeAnalysisService,
    detect_catalog_skills,
)
from app.services.resume_service import ResumeService
from app.services.resume_storage import ResumeStorage
from tests.ai.test_analysis_service import ScriptedProvider
from tests.resumes.fakes import (
    RESUME_LINES,
    FakeResumeAnalysisRepository,
    FakeResumeRepository,
    FakeSkillNames,
    make_docx,
    make_pdf,
    make_profiles,
)

USER = SimpleNamespace(id="u1")
OTHER = SimpleNamespace(id="u2")

FULL_RESUME = {
    "summary": "Backend engineer with 4 years in Python services.",
    "totalYearsExperience": 4,
    "experience": [
        {
            "title": "Backend Engineer",
            "company": "Acme Corp",
            "startDate": "2020",
            "endDate": "2024",
            "description": "Built Python and Postgres services",
            "highlights": ["led migration to Kubernetes"],
        },
        "not an object",
    ],
    "skills": ["Python", "Django"],
    "technologies": ["PostgreSQL", "Docker"],
    "projects": [],
    "education": [{"degree": "B.Tech Computer Science", "institution": "IIT Delhi", "year": "2019"}],
    "achievements": [],
    "confidence": 1.7,  # clamped
}


def make_harness(tmp_path: Path):
    settings = get_settings().model_copy(
        update={"llm_retry_base_delay_seconds": 0.0, "llm_timeout_seconds": 5.0}
    )
    analyses = FakeResumeAnalysisRepository()
    profiles = make_profiles("u1")
    resumes = FakeResumeRepository(analyses, profiles)
    storage = ResumeStorage(tmp_path)
    service = ResumeService(resumes=resumes, profiles=profiles, storage=storage, settings=settings)  # type: ignore[arg-type]
    return service, resumes, analyses, profiles, storage, settings


async def test_upload_creates_resume_version_file_and_auto_selects(tmp_path: Path) -> None:
    service, resumes, _, profiles, _, _ = make_harness(tmp_path)

    out = await service.upload(
        USER, filename="Priya_Sharma-CV.pdf", data=make_pdf(RESUME_LINES), title=None, resume_id=None  # type: ignore[arg-type]
    )

    assert out.title == "Priya Sharma CV"  # derived from the filename
    assert out.isSelected is True
    assert len(out.versions) == 1
    version = out.versions[0]
    assert version.versionNumber == 1 and version.analysis is None
    assert version.mimeType == "application/pdf"
    stored = resumes.versions[version.id]
    assert "PostgreSQL" in stored.extractedText
    assert (tmp_path / stored.storagePath).is_file()
    assert (await profiles.get_by_user_id("u1")).selectedResumeId == out.id


async def test_second_upload_adds_a_version_and_rejects_identical_file(tmp_path: Path) -> None:
    service, _, _, _, _, _ = make_harness(tmp_path)
    first = await service.upload(USER, filename="cv.pdf", data=make_pdf(["v1"]), title="Main", resume_id=None)  # type: ignore[arg-type]

    second = await service.upload(
        USER, filename="cv-v2.docx", data=make_docx(["v2 text"]), title=None, resume_id=first.id  # type: ignore[arg-type]
    )
    assert [v.versionNumber for v in second.versions] == [2, 1]
    assert second.latestVersionId == second.versions[0].id

    with pytest.raises(ConflictError):
        await service.upload(USER, filename="cv-v2.docx", data=make_docx(["v2 text"]), title=None, resume_id=first.id)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.upload(OTHER, filename="x.pdf", data=make_pdf(["x"]), title=None, resume_id=first.id)  # type: ignore[arg-type]


async def test_select_switches_and_delete_clears_selection_and_files(tmp_path: Path) -> None:
    service, resumes, _, profiles, _, _ = make_harness(tmp_path)
    a = await service.upload(USER, filename="a.pdf", data=make_pdf(["a"]), title="A", resume_id=None)  # type: ignore[arg-type]
    b = await service.upload(USER, filename="b.pdf", data=make_pdf(["b"]), title="B", resume_id=None)  # type: ignore[arg-type]
    assert (await profiles.get_by_user_id("u1")).selectedResumeId == a.id  # first upload wins

    selected = await service.select(USER, b.id)  # type: ignore[arg-type]
    assert selected.isSelected is True
    listed = await service.list(USER)  # type: ignore[arg-type]
    assert [r.isSelected for r in sorted(listed.items, key=lambda r: r.title)] == [False, True]
    assert listed.selectedResumeId == b.id

    with pytest.raises(NotFoundError):
        await service.select(OTHER, b.id)  # type: ignore[arg-type]

    path = tmp_path / resumes.versions[b.versions[0].id].storagePath
    await service.delete(USER, b.id)  # type: ignore[arg-type]
    assert not path.exists()
    assert (await profiles.get_by_user_id("u1")).selectedResumeId is None
    assert await service.selected_version(USER) is None  # type: ignore[arg-type]

    await service.select(USER, a.id)  # type: ignore[arg-type]
    current = await service.selected_version(USER)  # type: ignore[arg-type]
    assert current is not None and current.resumeId == a.id


async def test_version_access_is_owner_scoped(tmp_path: Path) -> None:
    service, _, _, _, _, _ = make_harness(tmp_path)
    out = await service.upload(USER, filename="a.pdf", data=make_pdf(["a"]), title="A", resume_id=None)  # type: ignore[arg-type]
    version_id = out.versions[0].id
    assert (await service.get_version(USER, version_id)).id == version_id  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.get_version(OTHER, version_id)  # type: ignore[arg-type]
    path, _ = await service.file_path(USER, version_id)  # type: ignore[arg-type]
    assert path.is_file()


# ── analysis ─────────────────────────────────────────────────────────────────


def make_analysis_service(provider, catalog: list[str] | None = None):
    settings = get_settings().model_copy(
        update={"llm_retry_base_delay_seconds": 0.0, "llm_timeout_seconds": 5.0}
    )
    analyses = FakeResumeAnalysisRepository()
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    service = ResumeAnalysisService(
        provider,
        analyses,  # type: ignore[arg-type]
        FakeSkillNames(catalog or ["Python", "Kubernetes", "Go", "C++"]),  # type: ignore[arg-type]
        settings,
        sleep=record_sleep,
    )
    return service, analyses, sleeps


def make_version(text: str = "\n".join(RESUME_LINES)):
    return SimpleNamespace(id="v1", resumeId="r1", extractedText=text)


async def test_analysis_stores_provenance_and_unions_catalog_skills() -> None:
    provider = ScriptedProvider([FULL_RESUME])
    service, _analyses, _ = make_analysis_service(provider)

    row = await service.analyze_version(make_version())  # type: ignore[arg-type]

    assert row.promptVersion == RESUME_PROMPT_VERSION
    assert row.model == "scripted" and row.inputTokens == 10
    assert row.confidence == 1.0  # clamped
    stored = row.analysis
    assert stored["experience"][0]["company"] == "Acme Corp"
    assert len(stored["experience"]) == 1  # non-object dropped
    # Kubernetes is in the text and the catalog but not in the LLM output → unioned;
    # Python is already there → not duplicated; Go/C++ are not in the text.
    assert stored["skills"] == ["Python", "Django", "Kubernetes"]
    assert stored["technologies"] == ["PostgreSQL", "Docker"]

    cached = await service.analyze_version(make_version())  # type: ignore[arg-type]
    assert cached.id == row.id and provider.calls == 1

    provider.script.append(FULL_RESUME)
    await service.analyze_version(make_version(), force=True)  # type: ignore[arg-type]
    assert provider.calls == 2


async def test_analysis_retries_then_surfaces_errors() -> None:
    provider = ScriptedProvider([LLMUnavailableError("down"), FULL_RESUME])
    service, _, sleeps = make_analysis_service(provider)
    await service.analyze_version(make_version())  # type: ignore[arg-type]
    assert provider.calls == 2 and sleeps == [0.0]

    bad = ScriptedProvider([{"skills": "not a list", "experience": 5}])
    service, _, _ = make_analysis_service(bad)
    row = await service.analyze_version(make_version())  # type: ignore[arg-type]
    assert row.analysis["skills"] == ["Python", "Kubernetes"]  # lenient: garbage → [] + catalog

    with pytest.raises(LLMResponseError):
        service, _, _ = make_analysis_service(ScriptedProvider([["not", "an", "object"]]))
        await service.analyze_version(make_version())  # type: ignore[arg-type]


def test_detect_catalog_skills_uses_word_boundaries() -> None:
    catalog = ["Go", "C++", "Java", "JavaScript", "Node.js"]
    text = "Wrote Go services, some C++ and JavaScript (Node.js). Not Javan."
    assert detect_catalog_skills(text, catalog) == ["Go", "C++", "JavaScript", "Node.js"]
