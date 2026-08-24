from datetime import UTC, datetime

import httpx
import pytest

from app.sources import SourceParseError, SourceSearchParams
from tests.sources.conftest import load_text_fixture, make_registry


def handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/categories/remote-programming-jobs.rss"
    return httpx.Response(200, text=load_text_fixture("weworkremotely.rss.xml"))


@pytest.fixture
def connector():
    return make_registry(handler).get("weworkremotely")


async def test_search_parses_feed_items(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams())

    assert len(raw_jobs) == 2
    assert raw_jobs[0].externalId == (
        "https://weworkremotely.com/remote-jobs/initech-senior-python-engineer"
    )


async def test_keyword_and_date_filtering(connector) -> None:
    by_keyword = await connector.search_jobs(SourceSearchParams(keywords=("python",)))
    assert len(by_keyword) == 1

    since = datetime(2026, 8, 10, tzinfo=UTC)
    by_date = await connector.search_jobs(SourceSearchParams(postedSince=since))
    assert len(by_date) == 1
    assert "initech" in (by_date[0].externalId or "")


async def test_normalize_splits_company_and_title(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams())
    job = connector.normalize_job(raw_jobs[0])

    assert job.companyName == "Initech"
    assert job.title == "Senior Python Engineer"
    assert job.location == "Anywhere in the World"
    assert job.remote is True
    assert job.description == "Own our FastAPI services end to end."
    assert job.postedAt == datetime(2026, 8, 18, 9, 15, tzinfo=UTC)
    # ?ref=rss tracking is stripped from the canonical URL.
    assert job.canonicalUrl == (
        "https://weworkremotely.com/remote-jobs/initech-senior-python-engineer"
    )
    assert connector.normalize_job(raw_jobs[0]) == job


async def test_invalid_xml_raises_parse_error() -> None:
    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="this is not xml <<<")

    connector = make_registry(bad).get("weworkremotely")
    with pytest.raises(SourceParseError):
        await connector.search_jobs(SourceSearchParams())
