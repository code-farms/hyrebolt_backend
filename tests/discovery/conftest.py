import pytest

from app.core.config import get_settings
from app.services.deduplication_service import DeduplicationService
from app.services.discovery_service import DiscoveryService
from app.services.normalization_service import NormalizationService
from tests.discovery.fakes import (
    FakeCompanyRepository,
    FakeJobRepository,
    FakeJobSourceRepository,
    FakeListingRepository,
    FakeRegistry,
    FakeSearchRunRepository,
    FakeSourceRow,
    StubConnector,
)
from tests.fakes import FakeRedis


class DiscoveryHarness:
    def __init__(self, connectors: dict[str, StubConnector], rows: list[FakeSourceRow]):
        self.registry = FakeRegistry(connectors)
        self.sources = FakeJobSourceRepository(rows)
        self.runs = FakeSearchRunRepository()
        self.jobs = FakeJobRepository()
        self.listings = FakeListingRepository()
        self.jobs.listings = self.listings
        self.companies = FakeCompanyRepository()
        self.redis = FakeRedis()
        self.sleeps: list[float] = []

        async def record_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        settings = get_settings().model_copy(
            update={
                "discovery_retry_base_delay_seconds": 0.0,
                "discovery_retry_jitter_seconds": 0.0,
                "discovery_source_timeout_seconds": 1.0,
            }
        )
        self.settings = settings
        self.service = DiscoveryService(
            registry=self.registry,  # type: ignore[arg-type]
            job_sources=self.sources,  # type: ignore[arg-type]
            search_runs=self.runs,  # type: ignore[arg-type]
            normalizer=NormalizationService(),
            deduper=DeduplicationService(
                jobs=self.jobs,  # type: ignore[arg-type]
                listings=self.listings,  # type: ignore[arg-type]
                companies=self.companies,  # type: ignore[arg-type]
                sources=self.sources,  # type: ignore[arg-type]
            ),
            redis_client=self.redis,  # type: ignore[arg-type]
            settings=settings,
            sleep=record_sleep,
        )


@pytest.fixture
def make_harness():
    def _make(connectors: dict[str, StubConnector], rows: list[FakeSourceRow] | None = None):
        if rows is None:
            rows = [FakeSourceRow(name=name) for name in connectors]
        return DiscoveryHarness(connectors, rows)

    return _make
