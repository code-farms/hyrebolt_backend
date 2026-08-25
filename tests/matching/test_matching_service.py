from typing import Any

from app.ai import LLMProvider
from app.ai.base import LLMResult
from app.ai.exceptions import LLMUnavailableError
from app.core.config import get_settings
from app.models import MatchFeedback, MatchRecommendation
from app.services.ai_matcher import MATCH_PROMPT_VERSION, AIMatcher
from app.services.candidate_matching_service import (
    CandidateMatchingService,
    recommendation_from_score,
)
from app.services.rule_based_matcher import SCORING_VERSION, RuleBasedMatcher
from tests.matching.fakes import (
    FakeAnalysisRepoForMatching,
    FakeJobLookup,
    FakeJobMatchRepository,
    FakeProfileRepoForMatching,
    make_match_job,
    make_profile,
)

AI_RESPONSE: dict[str, Any] = {
    "whyMatch": "Strong python overlap with the required stack.",
    "missingSkills": ["kubernetes"],
    "strengths": ["python", "apis"],
    "concerns": ["salary not stated"],
    "recommendation": "strong match",  # sloppy casing on purpose
}


class ScriptedProvider(LLMProvider):
    def __init__(self, script: list[dict[str, Any] | Exception]) -> None:
        self.script = list(script)
        self.calls = 0

    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return LLMResult(content=step, model="scripted")


class FakeUser:
    id = "u1"


def make_service(provider: LLMProvider, jobs: list | None = None):
    jobs_by_id = {job.id: job for job in (jobs or [])}
    matches = FakeJobMatchRepository(jobs_by_id)
    profile = make_profile(
        target_roles=["Backend Engineer"], skills=["Python"], years=4.0
    )
    service = CandidateMatchingService(
        matcher=RuleBasedMatcher(get_settings()),
        ai_matcher=AIMatcher(provider),
        matches=matches,  # type: ignore[arg-type]
        profiles=FakeProfileRepoForMatching(profile),  # type: ignore[arg-type]
        analyses=FakeAnalysisRepoForMatching(),  # type: ignore[arg-type]
        jobs=FakeJobLookup(jobs_by_id),  # type: ignore[arg-type]
    )
    return service, matches


async def test_match_stores_scores_ai_fields_and_provenance() -> None:
    provider = ScriptedProvider([AI_RESPONSE])
    job = make_match_job()
    service, _matches = make_service(provider, [job])

    row = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]

    assert 0 <= row.overallScore <= 100
    assert row.roleScore == 100.0
    assert row.scoringVersion == SCORING_VERSION
    assert row.promptVersion == MATCH_PROMPT_VERSION
    assert row.aiModel == "scripted"
    assert row.recommendation == MatchRecommendation.STRONG_MATCH  # normalized
    assert row.whyMatch and row.missingSkills == ["kubernetes"]


async def test_cache_hit_skips_provider() -> None:
    provider = ScriptedProvider([AI_RESPONSE])
    job = make_match_job()
    service, _ = make_service(provider, [job])

    first = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]
    second = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]

    assert provider.calls == 1
    assert second.id == first.id


async def test_force_rescoring_preserves_feedback() -> None:
    provider = ScriptedProvider([AI_RESPONSE, AI_RESPONSE])
    job = make_match_job()
    service, matches = make_service(provider, [job])

    row = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]
    await matches.set_feedback(row.id, MatchFeedback.INTERESTED)

    rescored = await service.match_job(FakeUser(), job, force=True)  # type: ignore[arg-type]

    assert provider.calls == 2
    assert rescored.feedback == MatchFeedback.INTERESTED  # survived the re-score


async def test_ai_down_still_stores_match_with_banded_recommendation() -> None:
    provider = ScriptedProvider([LLMUnavailableError("api down")])
    job = make_match_job()
    service, _ = make_service(provider, [job])

    row = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]

    assert row.overallScore > 0  # deterministic scoring unaffected
    assert row.aiModel is None and row.promptVersion is None
    assert row.whyMatch is None
    assert row.recommendation == recommendation_from_score(row.overallScore)


async def test_invalid_ai_recommendation_falls_back_to_band() -> None:
    provider = ScriptedProvider([{**AI_RESPONSE, "recommendation": "MAYBE_SOMETIME"}])
    job = make_match_job()
    service, _ = make_service(provider, [job])

    row = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]

    assert row.recommendation == recommendation_from_score(row.overallScore)
    assert row.whyMatch is not None  # rest of the AI output still used


async def test_ensure_matches_batch_skips_failures() -> None:
    jobs = [make_match_job(), make_match_job(title="Data Engineer")]
    provider = ScriptedProvider([AI_RESPONSE, LLMUnavailableError("down")])
    service, matches = make_service(provider, jobs)

    matched = await service.ensure_matches_for_user(FakeUser(), limit=10)  # type: ignore[arg-type]

    assert matched == 2  # AI-down still produces a match (AI optional)
    assert len(matches.rows) == 2


async def test_record_feedback_creates_match_when_missing() -> None:
    provider = ScriptedProvider([AI_RESPONSE])
    job = make_match_job()
    service, matches = make_service(provider, [job])

    row = await service.record_feedback(FakeUser(), job, MatchFeedback.NOT_RELEVANT)  # type: ignore[arg-type]

    assert row.feedback == MatchFeedback.NOT_RELEVANT
    assert row.feedbackAt is not None
    assert (FakeUser.id, job.id) in matches.rows


def test_recommendation_bands() -> None:
    assert recommendation_from_score(95) == MatchRecommendation.MUST_APPLY
    assert recommendation_from_score(80) == MatchRecommendation.STRONG_MATCH
    assert recommendation_from_score(60) == MatchRecommendation.CONSIDER
    assert recommendation_from_score(40) == MatchRecommendation.LOW_PRIORITY
    assert recommendation_from_score(10) == MatchRecommendation.IGNORE
