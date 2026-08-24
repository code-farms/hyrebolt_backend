from datetime import UTC, datetime

import pytest

from app.core.exceptions import InvalidInputError
from app.models import SearchRunStatus
from app.schemas.search import SearchQuery
from app.services.discovery_service import to_source_params
from app.sources import SourceAuthRequiredError, SourceRateLimitedError, SourceUnavailableError
from tests.discovery.fakes import (
    FakeSourceRow,
    StubConnector,
    make_normalized_job,
    make_stub_config,
)


def stub(name: str, **kwargs) -> StubConnector:
    return StubConnector(name, make_stub_config(name), **kwargs)


async def test_all_sources_succeed_completed(make_harness) -> None:
    harness = make_harness(
        {
            "alpha": stub("alpha", jobs=[make_normalized_job(source_name="alpha", title="A")]),
            "beta": stub("beta", jobs=[make_normalized_job(source_name="beta", title="B")]),
        }
    )

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.COMPLETED
    assert sorted(run.sourcesSucceeded) == ["alpha", "beta"]
    assert run.sourcesFailed == []
    assert run.jobsFound == 2 and run.jobsNew == 2 and run.jobsDuplicate == 0
    assert run.completedAt is not None


async def test_partial_failure_does_not_fail_the_run(make_harness) -> None:
    harness = make_harness(
        {
            "alpha": stub("alpha", jobs=[make_normalized_job(source_name="alpha")]),
            "beta": stub("beta", script=[SourceUnavailableError("beta", "down")] * 5),
        }
    )

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.PARTIAL
    assert run.sourcesSucceeded == ["alpha"]
    assert run.sourcesFailed == ["beta"]
    assert "beta: down" in (run.errorSummary or "")
    assert run.jobsNew == 1


async def test_all_sources_failing_is_failed(make_harness) -> None:
    harness = make_harness(
        {"alpha": stub("alpha", script=[SourceUnavailableError("alpha", "down")] * 5)}
    )

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.FAILED
    assert run.sourcesFailed == ["alpha"]


async def test_no_eligible_sources_completes_with_zeros(make_harness) -> None:
    harness = make_harness(
        {"alpha": stub("alpha")}, rows=[FakeSourceRow(name="alpha", enabled=False)]
    )

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.COMPLETED
    assert run.sourcesAttempted == []
    assert run.jobsFound == 0


async def test_requested_disabled_source_recorded_as_failed(make_harness) -> None:
    harness = make_harness(
        {
            "alpha": stub("alpha", jobs=[make_normalized_job(source_name="alpha")]),
            "beta": stub("beta"),
        },
        rows=[FakeSourceRow(name="alpha"), FakeSourceRow(name="beta", enabled=False)],
    )

    run = await harness.service.run_search(
        user_id="u1", query=SearchQuery(sources=["alpha", "beta"])
    )

    assert run.status == SearchRunStatus.PARTIAL
    assert set(run.sourcesAttempted) == {"alpha", "beta"}
    assert run.sourcesFailed == ["beta"]
    assert "beta: disabled" in (run.errorSummary or "")
    assert harness.registry._connectors["beta"].calls == 0


async def test_unknown_requested_source_fails_fast_without_a_run(make_harness) -> None:
    harness = make_harness({"alpha": stub("alpha")})

    with pytest.raises(InvalidInputError):
        await harness.service.run_search(
            user_id="u1", query=SearchQuery(sources=["alpha", "monsterboard"])
        )
    assert harness.runs.runs == {}


async def test_retryable_error_retries_then_succeeds(make_harness) -> None:
    connector = stub(
        "alpha",
        jobs=[make_normalized_job(source_name="alpha")],
        script=[SourceRateLimitedError("alpha", "slow down", retry_after=7.0), None],
    )
    harness = make_harness({"alpha": connector})

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.COMPLETED
    assert connector.calls == 2
    assert any(s >= 7.0 for s in harness.sleeps)  # retry_after honored as delay floor


async def test_non_retryable_error_attempts_once(make_harness) -> None:
    connector = stub("alpha", script=[SourceAuthRequiredError("alpha", "403")] * 5)
    harness = make_harness({"alpha": connector})

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.FAILED
    assert connector.calls == 1


async def test_retry_exhaustion_fails_source(make_harness) -> None:
    connector = stub("alpha", script=[SourceUnavailableError("alpha", "down")] * 10)
    harness = make_harness({"alpha": connector})

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.FAILED
    assert connector.calls == harness.settings.discovery_retry_attempts


async def test_slow_source_times_out_others_complete(make_harness) -> None:
    harness = make_harness(
        {
            "slow": stub("slow", delay_seconds=5.0),
            "fast": stub("fast", jobs=[make_normalized_job(source_name="fast")]),
        }
    )

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.PARTIAL
    assert run.sourcesSucceeded == ["fast"]
    assert run.sourcesFailed == ["slow"]
    assert "timed out" in (run.errorSummary or "")


async def test_throttle_wired_for_rate_limited_source(make_harness) -> None:
    harness = make_harness(
        {"alpha": stub("alpha")},
        rows=[FakeSourceRow(name="alpha", rateLimitPerMinute=10)],
    )

    await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert harness.registry.throttles["alpha"] is not None


def test_to_source_params_mapping() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    query = SearchQuery(
        keywords=["python", "api"],
        targetRoles=["Backend Engineer", "python"],  # deduped against keywords
        datePosted=7,
        limitPerSource=200,  # clamped by max_per_source below
    )

    params = to_source_params(query, max_per_source=50, now=now)

    assert params.keywords == ("python", "api", "Backend Engineer")
    assert params.postedSince == datetime(2026, 8, 18, tzinfo=UTC)
    assert params.limit == 50
