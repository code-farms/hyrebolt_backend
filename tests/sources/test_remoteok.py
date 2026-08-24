from datetime import UTC, datetime

import httpx
import pytest

from app.sources import SourceSearchParams, SourceUnavailableError
from app.utils.normalization import compute_content_hash
from tests.sources.conftest import load_json_fixture, make_registry


def handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api"
    return httpx.Response(200, json=load_json_fixture("remoteok.json"))


@pytest.fixture
def connector():
    return make_registry(handler).get("remoteok")


async def test_search_skips_legal_notice(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams())

    assert [raw.externalId for raw in raw_jobs] == ["1001", "1002"]
    assert all(raw.sourceName == "remoteok" for raw in raw_jobs)


async def test_search_filters_keywords_posted_since_and_limit(connector) -> None:
    by_keyword = await connector.search_jobs(SourceSearchParams(keywords=("python",)))
    assert [raw.externalId for raw in by_keyword] == ["1001"]

    since = datetime(2026, 8, 15, tzinfo=UTC)
    by_date = await connector.search_jobs(SourceSearchParams(postedSince=since))
    assert [raw.externalId for raw in by_date] == ["1001"]

    limited = await connector.search_jobs(SourceSearchParams(limit=1))
    assert len(limited) == 1

    onsite_only = await connector.search_jobs(SourceSearchParams(remote=False))
    assert onsite_only == []


async def test_normalize_job_fields(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams())
    job = connector.normalize_job(raw_jobs[0])

    assert job.title == "Backend Engineer"
    assert job.companyName == "Acme Robotics Inc."
    assert job.normalizedTitle == "backend engineer"
    assert job.description == "Build APIs in Python & Postgres."
    assert job.location == "Worldwide"
    assert job.remote is True
    assert job.salaryMin == 60000
    assert job.salaryMax == 90000
    assert job.salaryCurrency == "USD"
    assert job.postedAt == datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    assert job.sourceUrl == "https://remoteok.com/remote-jobs/1001?utm_source=feed"
    assert job.canonicalUrl == "https://remoteok.com/remote-jobs/1001"
    assert job.contentHash == compute_content_hash(
        normalized_title=job.normalizedTitle,
        company_name=job.companyName,
        normalized_location=job.normalizedLocation,
        description=job.description,
    )
    # Determinism: normalizing twice yields identical models.
    assert connector.normalize_job(raw_jobs[0]) == job


async def test_normalize_never_fabricates_missing_salary(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams())
    job = connector.normalize_job(raw_jobs[1])

    assert job.salaryMin is None
    assert job.salaryMax is None
    assert job.salaryCurrency is None
    assert job.location is None


async def test_upstream_error_is_retryable() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    connector = make_registry(failing).get("remoteok")
    with pytest.raises(SourceUnavailableError) as excinfo:
        await connector.search_jobs(SourceSearchParams())
    assert excinfo.value.retryable is True
