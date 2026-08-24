"""Two integration tests across the Phase 4/5 seam: the real SourceRegistry +
MockTransport driven end-to-end through the discovery pipeline, and the
throttle actually landing in SourceHTTPClient."""

import httpx

from app.core.config import get_settings
from app.models import SearchRunStatus
from app.schemas.search import SearchQuery
from app.services.deduplication_service import DeduplicationService
from app.services.discovery_service import DiscoveryService
from app.services.normalization_service import NormalizationService
from app.sources import DEFAULT_CONFIGS, SourceRegistry, SourceSearchParams
from tests.discovery.fakes import (
    FakeCompanyRepository,
    FakeJobRepository,
    FakeJobSourceRepository,
    FakeListingRepository,
    FakeSearchRunRepository,
    FakeSourceRow,
)
from tests.fakes import FakeRedis
from tests.sources.conftest import load_json_fixture


def remoteok_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api"
    return httpx.Response(200, json=load_json_fixture("remoteok.json"))


def build_service(registry: SourceRegistry, rows: list[FakeSourceRow]):
    jobs = FakeJobRepository()
    listings = FakeListingRepository()
    jobs.listings = listings
    sources = FakeJobSourceRepository(rows)
    settings = get_settings().model_copy(
        update={
            "discovery_retry_base_delay_seconds": 0.0,
            "discovery_retry_jitter_seconds": 0.0,
        }
    )

    async def no_sleep(_: float) -> None:
        return None

    service = DiscoveryService(
        registry=registry,
        job_sources=sources,  # type: ignore[arg-type]
        search_runs=FakeSearchRunRepository(),  # type: ignore[arg-type]
        normalizer=NormalizationService(),
        deduper=DeduplicationService(
            jobs=jobs,  # type: ignore[arg-type]
            listings=listings,  # type: ignore[arg-type]
            companies=FakeCompanyRepository(),  # type: ignore[arg-type]
            sources=sources,  # type: ignore[arg-type]
        ),
        redis_client=FakeRedis(),  # type: ignore[arg-type]
        settings=settings,
        sleep=no_sleep,
    )
    return service, jobs, listings


async def test_remoteok_fixture_flows_through_the_full_pipeline() -> None:
    registry = SourceRegistry(
        httpx.AsyncClient(transport=httpx.MockTransport(remoteok_handler))
    )
    service, jobs, listings = build_service(registry, [FakeSourceRow(name="remoteok")])

    run = await service.run_search(
        user_id="u1", query=SearchQuery(sources=["remoteok"], keywords=["python", "react"])
    )

    assert run.status == SearchRunStatus.COMPLETED
    assert run.jobsFound == 2 and run.jobsNew == 2
    assert len(jobs.jobs) == 2
    assert all(listing.isPrimary for listing in listings.listings)

    # Re-run: everything dedupes via the (sourceId, externalId) listing key.
    rerun = await service.run_search(user_id="u1", query=SearchQuery(sources=["remoteok"]))
    assert rerun.jobsNew == 0 and rerun.jobsDuplicate == 2


async def test_throttle_reaches_the_http_layer() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=load_json_fixture("remoteok.json"))

    throttle_calls = 0

    async def throttle() -> None:
        nonlocal throttle_calls
        throttle_calls += 1

    registry = SourceRegistry(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    connector = registry.connector_with_config(
        "remoteok", DEFAULT_CONFIGS["remoteok"], throttle=throttle
    )

    await connector.search_jobs(SourceSearchParams(limit=5))

    assert request_count == 1
    assert throttle_calls == 1  # awaited before the request
