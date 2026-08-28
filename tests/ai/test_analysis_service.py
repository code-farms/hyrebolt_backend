from typing import Any

import pytest

from app.ai import LLMProvider, LLMRateLimitedError, LLMResponseError, MockLLMProvider
from app.ai.base import LLMResult
from app.core.config import get_settings
from app.services.job_analysis_service import (
    PROMPT_VERSION,
    JobAnalysisService,
)
from tests.ai.fakes import FakeAnalysisRepository, FakeJob, FakeJobsForAnalysis

FULL_ANALYSIS: dict[str, Any] = {
    "title": "Backend Engineer",
    "seniority": "mid",
    "skillsRequired": ["python", "postgres"],
    "skillsPreferred": ["redis"],
    "experienceMin": 3,
    "experienceMax": 6,
    "location": "Bengaluru, India",
    "workMode": "hybrid",  # lowercase on purpose: validator normalizes
    "employmentType": "Full-time",
    "salary": {"min": 2000000, "max": 3000000, "currency": "INR"},
    "responsibilities": ["build APIs"],
    "techStack": ["python", "fastapi"],
    "industry": "SaaS",
    "confidence": 0.92,
}


class ScriptedProvider(LLMProvider):
    """Returns queued results/exceptions in order."""

    def __init__(self, script: list[dict[str, Any] | Exception]) -> None:
        self.script = list(script)
        self.calls = 0

    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return LLMResult(content=step, model="scripted", inputTokens=10, outputTokens=5)


def make_service(provider: LLMProvider, jobs: list[FakeJob] | None = None):
    analyses = FakeAnalysisRepository()
    job_repo = FakeJobsForAnalysis(jobs or [])
    job_repo.analyses = analyses
    settings = get_settings().model_copy(
        update={"llm_retry_base_delay_seconds": 0.0, "llm_timeout_seconds": 5.0}
    )
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    service = JobAnalysisService(
        provider=provider,
        analyses=analyses,  # type: ignore[arg-type]
        jobs=job_repo,  # type: ignore[arg-type]
        settings=settings,
        sleep=record_sleep,
    )
    return service, analyses, sleeps


async def test_analyze_stores_result_with_provenance() -> None:
    provider = ScriptedProvider([FULL_ANALYSIS])
    service, analyses, _ = make_service(provider)
    job = FakeJob()

    row = await service.analyze_job(job)  # type: ignore[arg-type]

    assert row.jobId == job.id
    assert row.model == "scripted"
    assert row.promptVersion == PROMPT_VERSION
    assert row.inputTokens == 10 and row.outputTokens == 5
    assert row.confidence == 0.92
    assert row.processedAt is not None
    stored = analyses.rows[job.id].analysis
    assert stored["workMode"] == "HYBRID"  # normalized
    assert stored["employmentType"] == "FULL_TIME"
    assert stored["salary"]["currency"] == "INR"


async def test_cache_hit_skips_provider() -> None:
    provider = ScriptedProvider([FULL_ANALYSIS])
    service, _, _ = make_service(provider)
    job = FakeJob()

    first = await service.analyze_job(job)  # type: ignore[arg-type]
    second = await service.analyze_job(job)  # type: ignore[arg-type]

    assert provider.calls == 1
    assert second.processedAt == first.processedAt


async def test_force_reanalyzes() -> None:
    provider = ScriptedProvider([FULL_ANALYSIS, FULL_ANALYSIS])
    service, _, _ = make_service(provider)
    job = FakeJob()

    await service.analyze_job(job)  # type: ignore[arg-type]
    await service.analyze_job(job, force=True)  # type: ignore[arg-type]

    assert provider.calls == 2


async def test_stale_prompt_version_reanalyzes() -> None:
    provider = ScriptedProvider([FULL_ANALYSIS, FULL_ANALYSIS])
    service, analyses, _ = make_service(provider)
    job = FakeJob()
    await service.analyze_job(job)  # type: ignore[arg-type]
    analyses.rows[job.id].promptVersion = "v0"  # simulate an old prompt

    await service.analyze_job(job)  # type: ignore[arg-type]

    assert provider.calls == 2
    assert analyses.rows[job.id].promptVersion == PROMPT_VERSION


async def test_nulls_are_preserved_never_invented() -> None:
    sparse = {"title": "Backend Engineer", "confidence": 0.4}  # everything else absent
    provider = ScriptedProvider([sparse])
    service, analyses, _ = make_service(provider)
    job = FakeJob()

    await service.analyze_job(job)  # type: ignore[arg-type]

    stored = analyses.rows[job.id].analysis
    assert stored["salary"] is None
    assert stored["experienceMin"] is None
    assert stored["workMode"] is None
    assert stored["skillsRequired"] == []


async def test_retryable_error_then_success() -> None:
    provider = ScriptedProvider([LLMRateLimitedError("slow down", retry_after=9.0), FULL_ANALYSIS])
    service, _, sleeps = make_service(provider)

    row = await service.analyze_job(FakeJob())  # type: ignore[arg-type]

    assert row.model == "scripted"
    assert provider.calls == 2
    assert any(s >= 9.0 for s in sleeps)  # retry_after honored


async def test_non_retryable_validation_error_raises() -> None:
    provider = ScriptedProvider([{"confidence": "not-even-a-number", "salary": 12}])
    service, _, _ = make_service(provider)

    with pytest.raises(LLMResponseError):
        await service.analyze_job(FakeJob())  # type: ignore[arg-type]
    # Schema validation runs after the retry loop: well-formed JSON with the
    # wrong shape is a prompt problem, so it is not re-requested.
    assert provider.calls == 1


async def test_analyze_unanalyzed_batch_skips_failures() -> None:
    jobs = [FakeJob(), FakeJob(), FakeJob()]
    # Job 2 returns corrupted JSON on every attempt (1 + llm_max_retries=2
    # retries) and is skipped; jobs 1 and 3 succeed.
    provider = ScriptedProvider(
        [FULL_ANALYSIS, *([LLMResponseError("garbage")] * 3), FULL_ANALYSIS]
    )
    service, analyses, _ = make_service(provider, jobs=jobs)

    analyzed = await service.analyze_unanalyzed(limit=10)

    assert analyzed == 2
    assert len(analyses.rows) == 2
    assert provider.calls == 5


async def test_mock_provider_end_to_end() -> None:
    service, analyses, _ = make_service(MockLLMProvider())
    job = FakeJob(title="Data Engineer")

    row = await service.analyze_job(job)  # type: ignore[arg-type]

    assert row.model == "mock"
    assert analyses.rows[job.id].analysis["title"] == "Data Engineer"
    assert analyses.rows[job.id].analysis["salary"] is None
