from datetime import UTC, datetime

import httpx
import pytest

from app.models import EmploymentType
from app.sources import (
    DEFAULT_CONFIGS,
    SourceSearchParams,
    SourceUnavailableError,
)
from tests.sources.conftest import load_json_fixture, make_registry

BOARDS = [
    {"company": "AcmeCorp", "provider": "greenhouse", "token": "acmecorp"},
    {"company": "Globex", "provider": "lever", "token": "globex"},
]


def config_with_boards():
    base = DEFAULT_CONFIGS["company_careers"]
    return {"company_careers": base.model_copy(update={"extra": {"boards": BOARDS}})}


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "boards-api.greenhouse.io":
        assert request.url.path == "/v1/boards/acmecorp/jobs"
        return httpx.Response(200, json=load_json_fixture("greenhouse.json"))
    if request.url.host == "api.lever.co":
        assert request.url.path == "/v0/postings/globex"
        return httpx.Response(200, json=load_json_fixture("lever.json"))
    raise AssertionError(f"unexpected host: {request.url}")


@pytest.fixture
def connector():
    return make_registry(handler, overrides=config_with_boards()).get("company_careers")


async def test_search_fetches_all_boards(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams())

    assert len(raw_jobs) == 3
    external_ids = {raw.externalId for raw in raw_jobs}
    assert "greenhouse:acmecorp:555001" in external_ids
    assert "lever:globex:abc-123-def" in external_ids


async def test_company_and_keyword_filters(connector) -> None:
    only_globex = await connector.search_jobs(SourceSearchParams(companies=("globex",)))
    assert [raw.externalId for raw in only_globex] == ["lever:globex:abc-123-def"]

    by_keyword = await connector.search_jobs(SourceSearchParams(keywords=("platform",)))
    assert [raw.externalId for raw in by_keyword] == ["greenhouse:acmecorp:555001"]


async def test_no_boards_returns_empty() -> None:
    connector = make_registry(handler).get("company_careers")  # default: empty boards
    assert await connector.search_jobs(SourceSearchParams()) == []


async def test_normalize_greenhouse(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams(companies=("acmecorp",)))
    job = connector.normalize_job(raw_jobs[0])

    assert job.title == "Platform Engineer"
    assert job.companyName == "AcmeCorp"
    assert job.location == "Remote - India"
    assert job.remote is True  # "remote" appears in the location
    assert job.description == "Design and run our platform infrastructure."
    assert job.postedAt == datetime(2026, 8, 15, 14, 30, tzinfo=UTC)
    # gh_src tracking param stripped:
    assert job.canonicalUrl == "https://boards.greenhouse.io/acmecorp/jobs/555001"


async def test_normalize_lever(connector) -> None:
    raw_jobs = await connector.search_jobs(SourceSearchParams(companies=("globex",)))
    job = connector.normalize_job(raw_jobs[0])

    assert job.title == "Senior Backend Engineer"
    assert job.companyName == "Globex"
    assert job.location == "Bengaluru, India"
    assert job.hybrid is True
    assert job.remote is False
    assert job.country == "IN"
    assert job.employmentType is EmploymentType.FULL_TIME
    assert job.description == "Own the core services powering Globex."
    assert job.postedAt == datetime.fromtimestamp(1786800000, tz=UTC)
    assert job.canonicalUrl == "https://jobs.lever.co/globex/abc-123-def"


async def test_partial_board_failure_returns_surviving_jobs() -> None:
    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.lever.co":
            return httpx.Response(500)
        return handler(request)

    connector = make_registry(flaky, overrides=config_with_boards()).get("company_careers")
    raw_jobs = await connector.search_jobs(SourceSearchParams())

    assert len(raw_jobs) == 2  # greenhouse jobs still delivered
    assert all(raw.externalId.startswith("greenhouse:") for raw in raw_jobs)


async def test_all_boards_failing_raises() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    connector = make_registry(down, overrides=config_with_boards()).get("company_careers")
    with pytest.raises(SourceUnavailableError):
        await connector.search_jobs(SourceSearchParams())
