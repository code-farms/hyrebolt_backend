from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.ai.exceptions import LLMUnavailableError
from app.core.config import get_settings
from app.schemas.resume import GapAIResult
from app.services.resume_gap_service import (
    GAP_PROMPT_VERSION,
    ResumeGapService,
    compute_skill_gap,
    ground,
    is_grounded,
)
from tests.ai.test_analysis_service import ScriptedProvider
from tests.resumes.fakes import (
    RESUME_LINES,
    FakeResumeAnalysisRow,
    FakeResumeGapRepository,
    FakeSkillNames,
    make_profiles,
)

USER = SimpleNamespace(id="u1")
NOW = datetime.now(UTC)

RESUME_TEXT = "\n".join(RESUME_LINES)
RESUME_ANALYSIS = {
    "summary": None,
    "totalYearsExperience": 4,
    "experience": [{"title": "Backend Engineer", "company": "Acme Corp", "highlights": []}],
    "skills": ["Python", "Django"],
    "technologies": ["PostgreSQL"],
    "projects": [],
    "education": [],
    "achievements": [],
    "confidence": 0.9,
}
JOB_ANALYSIS = {
    "skillsRequired": ["Python", "Postgres", "Kubernetes"],
    "skillsPreferred": ["Terraform"],
    "techStack": ["Docker"],
}


class FakeJobAnalysisService:
    def __init__(self, analysis: dict | None = JOB_ANALYSIS, *, fail: bool = False) -> None:
        self.analysis = analysis
        self.fail = fail
        self.processed_at = NOW - timedelta(hours=1)

    async def analyze_job(self, job, *, force: bool = False):
        if self.fail:
            raise LLMUnavailableError("down")
        return SimpleNamespace(analysis=self.analysis, processedAt=self.processed_at)


def make_version(*, with_analysis: bool = True, processed_at: datetime = NOW - timedelta(hours=1)):
    analysis = (
        FakeResumeAnalysisRow(
            id="a1", versionId="v1", analysis=RESUME_ANALYSIS, confidence=0.9, model="m",
            promptVersion="resume-v1", inputTokens=None, outputTokens=None, processedAt=processed_at,
        )
        if with_analysis
        else None
    )
    return SimpleNamespace(id="v1", resumeId="r1", extractedText=RESUME_TEXT, analysis=analysis)


def make_job(description: str = "We need Python, Kubernetes and Terraform. Postgres a plus."):
    return SimpleNamespace(id="j1", title="Platform Engineer", companyName="Globex", description=description)


def make_service(provider, *, job_analysis=None, profile_skills: list[str] | None = None):
    gaps = FakeResumeGapRepository()
    service = ResumeGapService(
        provider=provider,
        gaps=gaps,  # type: ignore[arg-type]
        job_analysis=job_analysis or FakeJobAnalysisService(),  # type: ignore[arg-type]
        profiles=make_profiles("u1", skills=profile_skills),  # type: ignore[arg-type]
        skills=FakeSkillNames(["Python", "Kubernetes", "Terraform", "Postgres", "Docker"]),  # type: ignore[arg-type]
        settings=get_settings().model_copy(update={"llm_timeout_seconds": 5.0}),
    )
    return service, gaps


GOOD_AI = {
    "relevantExperience": [
        {"title": "Backend Engineer", "company": "Acme Corp", "why": "Python services at scale"},
        {"title": "CTO", "company": "Initech", "why": "invented"},  # not in the resume → dropped
    ],
    "weakAreas": [{"area": "Terraform", "why": "No IaC experience listed"}, {"area": "", "why": "x"}],
    "suggestedImprovements": [
        {
            "suggestion": "Lead with the Kubernetes migration.",
            "why": "The job's stack is Kubernetes-heavy.",
            "basedOn": "led migration to   Kubernetes",  # whitespace-mangled quote → kept
        },
        {
            "suggestion": "Mention your AWS certification.",
            "why": "Cloud is required.",
            "basedOn": "AWS Certified Solutions Architect",  # not in resume/profile → dropped
        },
        {
            "suggestion": "Add Docker to the skills line.",
            "why": "Docker is in the stack.",
            "basedOn": "Docker",  # profile-grounded (skill) → kept
        },
    ],
}


def test_compute_skill_gap_uses_aliases_and_keeps_job_wording() -> None:
    matched, missing = compute_skill_gap(
        ["python", "PostgreSQL", "Docker", "Docker"],
        ["Python", "Postgres", "Kubernetes", "docker", "Docker", "Terraform"],
    )
    assert matched == ["Python", "Postgres", "docker"]
    assert missing == ["Kubernetes", "Terraform"]


def test_is_grounded_accepts_substring_and_token_overlap_only() -> None:
    from app.services.resume_gap_service import _tokens
    from app.utils.normalization import normalize_title

    hay = normalize_title(RESUME_TEXT)
    tokens = set(_tokens(RESUME_TEXT))
    assert is_grounded("led migration to Kubernetes", hay, tokens)
    assert is_grounded("Led   migration -> Kubernetes!", hay, tokens)  # normalised
    assert is_grounded("built python postgres services quickly", hay, tokens)  # 4/5 tokens
    assert not is_grounded("AWS Certified Solutions Architect", hay, tokens)
    assert not is_grounded("", hay, tokens) and not is_grounded(None, hay, tokens)


def test_ground_drops_ungrounded_items() -> None:
    kept, dropped = ground(
        GapAIResult.model_validate(GOOD_AI),
        resume_text=RESUME_TEXT,
        profile_facts="Docker",
        experience=RESUME_ANALYSIS["experience"],
    )
    assert [e.company for e in kept.relevantExperience] == ["Acme Corp"]
    assert [w.area for w in kept.weakAreas] == ["Terraform"]
    assert [s.basedOn for s in kept.suggestedImprovements] == ["led migration to   Kubernetes", "Docker"]
    assert dropped == 3


async def test_gap_is_deterministic_plus_grounded_ai_and_cached() -> None:
    provider = ScriptedProvider([GOOD_AI])
    service, gaps = make_service(provider, profile_skills=["Docker"])

    out = await service.analyze(USER, make_version(), make_job())  # type: ignore[arg-type]

    result = out.result
    assert result.matchedSkills == ["Python", "Postgres", "Kubernetes", "Docker"]  # Kubernetes via text
    assert result.missingSkills == ["Terraform"]
    assert result.aiAvailable is True
    assert [e.company for e in result.relevantExperience] == ["Acme Corp"]
    assert len(result.suggestedImprovements) == 2
    assert all(s.why for s in result.suggestedImprovements)
    assert out.promptVersion == GAP_PROMPT_VERSION and out.model == "scripted"
    assert ("v1", "j1") in gaps.rows

    again = await service.analyze(USER, make_version(), make_job())  # type: ignore[arg-type]
    assert provider.calls == 1  # cache hit
    assert again.result.suggestedImprovements == result.suggestedImprovements

    provider.script.append(GOOD_AI)
    await service.analyze(USER, make_version(), make_job(), force=True)  # type: ignore[arg-type]
    assert provider.calls == 2


async def test_stale_cache_is_refreshed_when_resume_reanalyzed() -> None:
    provider = ScriptedProvider([GOOD_AI, GOOD_AI])
    service, _ = make_service(provider)
    await service.analyze(USER, make_version(), make_job())  # type: ignore[arg-type]
    newer = make_version(processed_at=datetime.now(UTC) + timedelta(seconds=5))
    await service.analyze(USER, newer, make_job())  # type: ignore[arg-type]
    assert provider.calls == 2


async def test_ai_failure_keeps_deterministic_result() -> None:
    service, _ = make_service(ScriptedProvider([LLMUnavailableError("down")]))
    out = await service.analyze(USER, make_version(), make_job())  # type: ignore[arg-type]
    assert out.result.aiAvailable is False
    assert out.result.matchedSkills == ["Python", "Postgres", "Kubernetes", "Docker"]
    assert out.result.suggestedImprovements == [] and out.model is None


async def test_without_job_analysis_falls_back_to_catalog_scan() -> None:
    service, _ = make_service(
        ScriptedProvider([LLMUnavailableError("down")]),
        job_analysis=FakeJobAnalysisService(fail=True),
    )
    out = await service.analyze(USER, make_version(with_analysis=False), make_job())  # type: ignore[arg-type]
    # Job skills come from the description; resume skills from the text scan.
    assert set(out.result.matchedSkills) == {"Python", "Kubernetes", "Postgres"}
    assert out.result.missingSkills == ["Terraform"]
