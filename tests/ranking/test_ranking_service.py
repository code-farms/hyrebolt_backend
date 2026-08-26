from types import SimpleNamespace

from app.models import PreferenceSignalKind as K
from app.repositories.job_repository import JobFilters
from app.services.ranking_service import DEFAULT_WEIGHTS, RankingService, RankingWeights
from tests.ranking.fakes import (
    FakeCandidateMatches,
    FakeJobsByScore,
    make_job,
    make_match,
    make_signal_service,
)

USER = SimpleNamespace(id="u1")


async def make_ranked_world():
    acme_backend = make_job(job_id="j-acme", title="Backend Engineer", company="Acme", posted_days_ago=30)
    globex_backend = make_job(job_id="j-globex", title="Backend Engineer", company="Globex", posted_days_ago=30)
    design = make_job(job_id="j-design", title="Product Designer", company="Zed", posted_days_ago=30)
    initech = make_job(job_id="j-initech", title="Backend Engineer", company="Initech", posted_days_ago=30)
    rows = [
        make_match(design, score=88),
        make_match(globex_backend, score=80),
        make_match(acme_backend, score=78),
        make_match(initech, score=85),
    ]
    signals, _ = make_signal_service()
    liked = make_job(job_id="j-liked", title="Backend Engineer", company="Acme", posted_days_ago=30)
    await signals.record(USER, liked, K.SAVE)  # type: ignore[arg-type]
    await signals.record(USER, liked, K.LIKE)  # type: ignore[arg-type]
    hidden = make_job(job_id="j-hide", company="Initech")
    await signals.record(USER, hidden, K.HIDE_COMPANY)  # type: ignore[arg-type]
    matches = FakeCandidateMatches(rows, applied_job_ids={"j-applied"})
    return matches, signals, rows


async def test_recommended_reorders_excludes_and_paginates_from_offset_zero() -> None:
    matches, signals, _ = await make_ranked_world()
    service = RankingService(matches, jobs=None, signals=signals)  # type: ignore[arg-type]

    page1, total = await service.recommended(USER, limit=2, offset=0, min_score=0)  # type: ignore[arg-type]
    page2, _ = await service.recommended(USER, limit=2, offset=2, min_score=0)  # type: ignore[arg-type]

    assert total == 3  # Initech hidden
    ids = [r.match.jobId for r in [*page1, *page2]]
    # Acme backend (78 + role 6 + company 4 ≈ 88) ties/beats design (88) on final, base breaks ties
    assert ids[0] in ("j-acme", "j-design") and set(ids) == {"j-acme", "j-design", "j-globex"}
    acme = next(r for r in [*page1, *page2] if r.match.jobId == "j-acme")
    assert acme.ranking.preferenceScore > 0
    assert any("roles like" in e for e in acme.ranking.explanations)
    assert any("jobs at Acme" in e for e in acme.ranking.explanations)
    assert matches.calls[-1] == {"min_score": 0, "limit": DEFAULT_WEIGHTS.candidate_limit}


async def test_recommended_without_signal_service_is_base_only() -> None:
    matches, _, _rows = await make_ranked_world()
    service = RankingService(matches)  # type: ignore[arg-type]
    ranked, total = await service.recommended(USER, limit=10, offset=0, min_score=0)  # type: ignore[arg-type]
    assert total == 4  # nothing hidden without learned preferences
    assert [r.match.overallScore for r in ranked] == [88, 85, 80, 78]
    assert all(r.ranking.finalScore == r.match.overallScore for r in ranked)


async def test_ranked_jobs_keeps_everything_and_db_total() -> None:
    matches, signals, rows = await make_ranked_world()
    service = RankingService(
        matches,  # type: ignore[arg-type]
        jobs=FakeJobsByScore(rows),  # type: ignore[arg-type]
        signals=signals,
        weights=RankingWeights(candidate_limit=10),
    )
    ranked, total = await service.ranked_jobs(USER, JobFilters(), min_score=0, limit=10, offset=0)  # type: ignore[arg-type]
    assert total == 4
    assert {r.match.jobId for r in ranked} == {"j-acme", "j-design", "j-globex", "j-initech"}  # hidden kept
    assert all(r.ranking is not None for r in ranked)


async def test_candidate_limit_bounds_the_window() -> None:
    matches, signals, _ = await make_ranked_world()
    service = RankingService(matches, signals=signals, weights=RankingWeights(candidate_limit=2))  # type: ignore[arg-type]
    ranked, total = await service.recommended(USER, limit=10, offset=0, min_score=0)  # type: ignore[arg-type]
    assert total <= 2 and len(ranked) == total
    assert matches.calls[-1]["limit"] == 2
