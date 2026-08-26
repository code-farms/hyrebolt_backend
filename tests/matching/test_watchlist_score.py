"""Phase 13: the deterministic watchlist component and its wiring through
CandidateMatchingService."""

from app.core.config import get_settings
from app.services.ai_matcher import AIMatcher
from app.services.candidate_matching_service import (
    CandidateMatchingService,
    to_watchlist_entries,
)
from app.services.rule_based_matcher import (
    WATCHLIST_BASE,
    RuleBasedMatcher,
    WatchlistEntry,
)
from tests.matching.fakes import (
    FakeAnalysisRepoForMatching,
    FakeJobLookup,
    FakeJobMatchRepository,
    FakeProfileRepoForMatching,
    FakeWatchlistRepoForMatching,
    make_match_job,
    make_profile,
    make_watchlist_row,
)
from tests.matching.test_matching_service import AI_RESPONSE, FakeUser, ScriptedProvider

settings = get_settings()
matcher = RuleBasedMatcher(settings)
profile = make_profile(target_roles=["Backend Engineer"])


def entry(
    *,
    company_id: str = "c1",
    name: str = "acme",
    priority: str = "HIGH",
    preferred: tuple[str, ...] = (),
    excluded: tuple[str, ...] = (),
) -> WatchlistEntry:
    return WatchlistEntry(
        companyId=company_id,
        normalizedName=name,
        priority=priority,
        preferredRoles=preferred,
        excludedRoles=excluded,
    )


def test_unwatched_company_has_no_signal_and_unchanged_overall() -> None:
    job = make_match_job(company="Globex", company_id="c9")

    overall_plain, plain = matcher.score(profile, job, None)  # type: ignore[arg-type]
    overall_watch, scored = matcher.score(profile, job, None, [entry()])  # type: ignore[arg-type]

    assert plain.watchlist is None and scored.watchlist is None
    assert overall_plain == overall_watch


def test_priority_sets_the_base_score() -> None:
    job = make_match_job(company="Acme", company_id="c1")
    for priority, expected in WATCHLIST_BASE.items():
        _, scores = matcher.score(profile, job, None, [entry(priority=priority)])  # type: ignore[arg-type]
        assert scores.watchlist == expected


def test_watched_company_raises_overall_score() -> None:
    job = make_match_job(company="Acme", company_id="c1")
    overall_plain, _ = matcher.score(profile, job, None)  # type: ignore[arg-type]
    overall_high, _ = matcher.score(profile, job, None, [entry(priority="HIGH")])  # type: ignore[arg-type]
    assert overall_high > overall_plain


def test_preferred_role_bonus_and_penalty() -> None:
    job = make_match_job(title="Senior Backend Engineer", company="Acme", company_id="c1")

    _, hit = matcher.score(profile, job, None, [entry(priority="MEDIUM", preferred=("Backend Engineer",))])  # type: ignore[arg-type]
    _, miss = matcher.score(profile, job, None, [entry(priority="MEDIUM", preferred=("Product Designer",))])  # type: ignore[arg-type]
    _, capped = matcher.score(profile, job, None, [entry(priority="HIGH", preferred=("Backend Engineer",))])  # type: ignore[arg-type]

    assert hit.watchlist == 85.0
    assert miss.watchlist == 60.0
    assert capped.watchlist == 100.0  # 90 + 10, capped


def test_excluded_role_zeroes_the_component() -> None:
    job = make_match_job(title="Sales Development Representative", company="Acme", company_id="c1")
    _, scores = matcher.score(profile, job, None, [entry(excluded=("Sales",))])  # type: ignore[arg-type]
    assert scores.watchlist == 0.0


def test_falls_back_to_normalized_name_when_company_id_missing() -> None:
    job = make_match_job(company="Acme Inc.", company_id=None)
    _, scores = matcher.score(profile, job, None, [entry(company_id="c1", name="acme", priority="LOW")])  # type: ignore[arg-type]
    assert scores.watchlist == WATCHLIST_BASE["LOW"]


def test_to_watchlist_entries_reads_included_company() -> None:
    rows = [make_watchlist_row(company_name="Acme Pvt Ltd", priority="LOW", preferred_roles=["SDE"])]
    (converted,) = to_watchlist_entries(rows)  # type: ignore[arg-type]
    assert converted.companyId == "c1"
    assert converted.normalizedName == "acme"
    assert converted.priority == "LOW"
    assert converted.preferredRoles == ("SDE",)


def make_service(provider, jobs, watchlist_rows):
    jobs_by_id = {job.id: job for job in jobs}
    matches = FakeJobMatchRepository(jobs_by_id)
    service = CandidateMatchingService(
        matcher=RuleBasedMatcher(settings),
        ai_matcher=AIMatcher(provider),
        matches=matches,  # type: ignore[arg-type]
        profiles=FakeProfileRepoForMatching(profile),  # type: ignore[arg-type]
        analyses=FakeAnalysisRepoForMatching(),  # type: ignore[arg-type]
        jobs=FakeJobLookup(jobs_by_id),  # type: ignore[arg-type]
        watchlists=FakeWatchlistRepoForMatching(watchlist_rows),  # type: ignore[arg-type]
    )
    return service, matches


async def test_service_persists_watchlist_score() -> None:
    job = make_match_job(company="Acme", company_id="c1")
    service, _ = make_service(ScriptedProvider([AI_RESPONSE]), [job], [make_watchlist_row()])

    row = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]

    assert row.watchlistScore == WATCHLIST_BASE["HIGH"]


async def test_service_without_watchlist_repo_stores_null() -> None:
    job = make_match_job(company="Acme", company_id="c1")
    jobs_by_id = {job.id: job}
    service = CandidateMatchingService(
        matcher=RuleBasedMatcher(settings),
        ai_matcher=AIMatcher(ScriptedProvider([AI_RESPONSE])),
        matches=FakeJobMatchRepository(jobs_by_id),  # type: ignore[arg-type]
        profiles=FakeProfileRepoForMatching(profile),  # type: ignore[arg-type]
        analyses=FakeAnalysisRepoForMatching(),  # type: ignore[arg-type]
        jobs=FakeJobLookup(jobs_by_id),  # type: ignore[arg-type]
    )
    row = await service.match_job(FakeUser(), job)  # type: ignore[arg-type]
    assert row.watchlistScore is None


async def test_rescore_company_forces_recompute_for_that_company_only() -> None:
    acme = make_match_job(company="Acme", company_id="c1")
    other = make_match_job(company="Globex", company_id="c2")
    provider = ScriptedProvider([AI_RESPONSE] * 4)
    watchlist = FakeWatchlistRepoForMatching([])
    service, matches = make_service(provider, [acme, other], [])
    service._watchlists = watchlist  # type: ignore[assignment]

    await service.match_job(FakeUser(), acme)  # type: ignore[arg-type]
    await service.match_job(FakeUser(), other)  # type: ignore[arg-type]
    assert matches.rows[("u1", acme.id)].watchlistScore is None

    watchlist.rows.append(make_watchlist_row(priority="MEDIUM"))
    rescored = await service.rescore_company(FakeUser(), "c1", limit=10)  # type: ignore[arg-type]

    assert rescored == 1
    assert provider.calls == 3  # only Acme was re-scored
    assert matches.rows[("u1", acme.id)].watchlistScore == WATCHLIST_BASE["MEDIUM"]
    assert matches.rows[("u1", other.id)].watchlistScore is None
