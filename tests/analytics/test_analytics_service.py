from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.core.exceptions import InvalidInputError
from app.services.analytics_service import AnalyticsService, build_window, rate
from tests.analytics.fakes import FakeAnalyticsRepository, engagement

USER = SimpleNamespace(id="u1")
# 01:30 UTC on 28 Aug = 07:00 IST the same day.
NOW = datetime(2026, 8, 28, 1, 30, tzinfo=UTC)


def make_service(**overrides) -> tuple[AnalyticsService, FakeAnalyticsRepository]:
    settings = get_settings().model_copy(update={"timezone": "Asia/Kolkata", **overrides})
    repo = FakeAnalyticsRepository()
    return AnalyticsService(repo, settings=settings), repo  # type: ignore[arg-type]


def test_rate_rounds_and_guards_zero() -> None:
    assert rate(1, 3) == 33.3
    assert rate(2, 2) == 100.0
    assert rate(0, 0) == 0.0
    assert rate(5, 0) == 0.0


def test_window_is_local_calendar_days_ending_today() -> None:
    window = build_window(7, "Asia/Kolkata", NOW)

    assert window.tz_name == "Asia/Kolkata"
    assert window.until_local.isoformat() == "2026-08-28"
    assert window.since_local.isoformat() == "2026-08-22"
    # IST midnight on the 22nd is 18:30 UTC on the 21st.
    assert window.since_utc == datetime(2026, 8, 21, 18, 30, tzinfo=UTC)
    assert [d.isoformat() for d in window.days()][::3] == ["2026-08-22", "2026-08-25", "2026-08-28"]


def test_window_falls_back_to_utc_for_unknown_timezone() -> None:
    window = build_window(30, "Mars/Olympus", NOW)

    assert window.tz_name == "UTC"
    assert window.since_utc == datetime(2026, 7, 30, tzinfo=UTC)
    assert len(window.days()) == 30


async def test_overview_rejects_unknown_range() -> None:
    service, _ = make_service()
    with pytest.raises(InvalidInputError):
        await service.overview(USER, 14)


async def test_overview_passes_window_threshold_and_limit_to_repository() -> None:
    service, repo = make_service(analytics_relevant_min_score=80.0, analytics_company_limit=1)

    result = await service.overview(USER, 7, now=NOW)

    since = datetime(2026, 8, 21, 18, 30, tzinfo=UTC)
    calls = dict(repo.calls)
    assert calls["discovery_counts"] == ("u1", since, 80.0)
    assert calls["deduplicated_count"] == (since,)
    assert calls["application_funnel"] == ("u1", since)
    assert calls["company_performance"] == ("u1", since, 80.0, 1)
    assert calls["daily_jobs"] == ("u1", since, "Asia/Kolkata", 80.0)
    assert calls["daily_application_events"] == ("u1", since, "Asia/Kolkata")
    assert result.range == 7
    assert result.timezone == "Asia/Kolkata"
    assert result.relevantMinScore == 80.0
    assert result.since == since
    assert result.until == NOW
    assert len(result.companies) == 1


async def test_overview_derives_discovery_and_funnel_rates() -> None:
    service, _ = make_service()

    result = await service.overview(USER, 30, now=NOW)

    assert result.discovery.model_dump() == {
        "jobsDiscovered": 40,
        "jobsDeduplicated": 12,
        "jobsAnalyzed": 30,
        "jobsMatched": 10,
        "analyzedRate": 75.0,
        "matchedRate": 25.0,
    }
    assert result.applications.model_dump() == {
        "saved": 8,
        "applied": 6,
        "interviews": 2,
        "offers": 1,
        "rejected": 3,
        "applyRate": 75.0,
        "interviewRate": 33.3,
        "offerRate": 16.7,
    }


async def test_overview_source_rates_are_zero_guarded() -> None:
    service, _ = make_service()

    result = await service.overview(USER, 30, now=NOW)

    remoteok, linkedin = result.sources
    assert (remoteok.relevanceRate, remoteok.applyRate, remoteok.interviewRate) == (26.7, 50.0, 50.0)
    assert linkedin.model_dump() == {
        "name": "linkedin",
        "displayName": "LinkedIn",
        "jobsFound": 10,
        "relevantJobs": 2,
        "saved": 1,
        "applied": 0,
        "interviews": 0,
        "relevanceRate": 20.0,
        "applyRate": 0.0,
        "interviewRate": 0.0,
    }


async def test_overview_folds_titles_into_role_families() -> None:
    service, _ = make_service()

    result = await service.overview(USER, 30, now=NOW)

    assert [(r.family, r.label, r.jobsFound) for r in result.roles] == [
        ("backend", "Backend", 20),  # senior backend engineer + python developer
        ("frontend", "Frontend", 6),
        ("other", "Other", 3),
    ]
    backend = result.roles[0]
    assert (backend.relevantJobs, backend.saved, backend.applied, backend.interviews) == (7, 3, 3, 1)
    assert (backend.relevanceRate, backend.applyRate) == (35.0, 42.9)


async def test_overview_company_rows_keep_null_company_id() -> None:
    service, _ = make_service()

    result = await service.overview(USER, 30, now=NOW)

    assert [(c.companyId, c.companyName, c.applied) for c in result.companies] == [
        ("c1", "Acme", 2),
        (None, "Globex", 0),
    ]


async def test_overview_zero_fills_timeseries_and_merges_event_days() -> None:
    service, repo = make_service()
    repo.daily_jobs_rows = [
        {"day": "2026-08-22", "discovered": 5, "matched": 2},
        {"day": "2026-08-28", "discovered": 1, "matched": 0},
    ]
    repo.daily_event_rows = [{"day": "2026-08-25", "applied": 2, "interviews": 1}]

    result = await service.overview(USER, 7, now=NOW)

    assert [p.date for p in result.timeseries] == [
        "2026-08-22",
        "2026-08-23",
        "2026-08-24",
        "2026-08-25",
        "2026-08-26",
        "2026-08-27",
        "2026-08-28",
    ]
    assert result.timeseries[0].model_dump() == {
        "date": "2026-08-22",
        "jobsDiscovered": 5,
        "jobsMatched": 2,
        "applied": 0,
        "interviews": 0,
    }
    assert result.timeseries[3].model_dump() == {
        "date": "2026-08-25",
        "jobsDiscovered": 0,
        "jobsMatched": 0,
        "applied": 2,
        "interviews": 1,
    }
    assert result.timeseries[6].jobsDiscovered == 1


async def test_overview_with_no_data_is_all_zeros() -> None:
    service, repo = make_service()
    repo.discovery = {"discovered": 0, "analyzed": 0, "matched": 0}
    repo.deduplicated = 0
    repo.funnel = dict.fromkeys(("saved", "applied", "interviews", "offers", "rejected"), 0)
    repo.sources = [{"name": "remoteok", "displayName": "Remote OK", **engagement(0)}]
    repo.titles = []
    repo.companies = []

    result = await service.overview(USER, 90, now=NOW)

    assert result.discovery.jobsDiscovered == 0 and result.discovery.matchedRate == 0.0
    assert result.applications.applyRate == 0.0
    assert result.sources[0].relevanceRate == 0.0
    assert result.roles == [] and result.companies == []
    assert len(result.timeseries) == 90
    assert all(p.jobsDiscovered == 0 for p in result.timeseries)
