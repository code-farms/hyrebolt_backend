import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from app.sources.exceptions import SourceError
from app.sources.http import SourceHTTPClient
from app.sources.models import (
    JobSourceConfig,
    NormalizedJob,
    RawJob,
    SourceHealth,
    SourceSearchParams,
)


class JobSourceConnector(ABC):
    """One job platform. Implementations must follow the compliance rules in
    docs/job-sources.md: official APIs / permitted feeds only, no auth or
    anti-bot circumvention. A source without a legitimate access path ships as
    a DisabledConnector, never a fake implementation."""

    def __init__(self, config: JobSourceConfig, http: SourceHTTPClient) -> None:
        self._config = config
        self._http = http

    @property
    def config(self) -> JobSourceConfig:
        return self._config

    def get_source_name(self) -> str:
        return self._config.name

    @abstractmethod
    async def search_jobs(self, params: SourceSearchParams) -> list[RawJob]:
        """Fetch raw postings. Filters the upstream can't apply are ignored
        here and re-applied by the pipeline after normalization."""

    async def get_job_details(self, raw: RawJob) -> RawJob:
        """Default: search already returned full detail (true for every
        currently implemented source) — identity. Detail-fetch sources
        override using raw.url / raw.externalId."""
        return raw

    @abstractmethod
    def normalize_job(self, raw: RawJob) -> NormalizedJob:
        """Pure and deterministic: no I/O, no clock, no randomness. Missing
        data maps to None — never fabricated."""

    async def health_check(self) -> SourceHealth:
        """Timed GET of baseUrl. Never raises; failures are reported in the
        result."""
        checked_at = datetime.now(UTC)
        if not self._config.enabled:
            return SourceHealth(
                sourceName=self.get_source_name(),
                healthy=False,
                checkedAt=checked_at,
                detail="disabled",
            )
        if not self._config.baseUrl:
            return SourceHealth(
                sourceName=self.get_source_name(),
                healthy=False,
                checkedAt=checked_at,
                detail="no baseUrl configured",
            )
        started = time.monotonic()
        try:
            await self._http.get_text(self._config.baseUrl)
        except SourceError as exc:
            return SourceHealth(
                sourceName=self.get_source_name(),
                healthy=False,
                checkedAt=checked_at,
                latencyMs=(time.monotonic() - started) * 1000,
                detail=exc.message,
            )
        return SourceHealth(
            sourceName=self.get_source_name(),
            healthy=True,
            checkedAt=checked_at,
            latencyMs=(time.monotonic() - started) * 1000,
        )
