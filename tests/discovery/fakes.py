"""In-memory fakes for the discovery pipeline tests."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models import SearchRunStatus, SearchTrigger
from app.sources import (
    JobSourceConfig,
    NormalizedJob,
    RawJob,
    SourceSearchParams,
)
from app.utils.normalization import (
    compute_content_hash,
    normalize_location,
    normalize_title,
)


def make_normalized_job(
    *,
    source_name: str = "remoteok",
    external_id: str | None = None,
    title: str = "Backend Engineer",
    company: str = "Acme",
    location: str | None = "Remote",
    canonical_url: str | None = None,
    description: str | None = "Build APIs",
    remote: bool = True,
    salary_max: int | None = None,
    salary_currency: str | None = None,
    experience_min: float | None = None,
    experience_max: float | None = None,
    posted_at: datetime | None = None,
) -> NormalizedJob:
    normalized_title = normalize_title(title)
    normalized_location = normalize_location(location)
    return NormalizedJob(
        sourceName=source_name,
        externalId=external_id,
        sourceUrl=canonical_url,
        canonicalUrl=canonical_url,
        title=title,
        normalizedTitle=normalized_title,
        description=description,
        companyName=company,
        location=location,
        normalizedLocation=normalized_location,
        remote=remote,
        salaryMax=salary_max,
        salaryCurrency=salary_currency,
        experienceMin=experience_min,
        experienceMax=experience_max,
        postedAt=posted_at,
        contentHash=compute_content_hash(
            normalized_title=normalized_title,
            company_name=company,
            normalized_location=normalized_location,
            description=description,
        ),
    )


@dataclass
class FakeSourceRow:
    name: str
    enabled: bool = True
    baseUrl: str | None = None
    rateLimitPerMinute: int | None = None
    requiresAuth: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


class FakeJobSourceRepository:
    def __init__(self, rows: list[FakeSourceRow]) -> None:
        self.rows = {row.name: row for row in rows}

    async def list_all(self) -> list[FakeSourceRow]:
        return list(self.rows.values())

    async def get_by_name(self, name: str) -> FakeSourceRow | None:
        return self.rows.get(name)


@dataclass
class FakeJobRow:
    id: str
    contentHash: str
    canonicalUrl: str | None
    companyId: str | None


@dataclass
class FakeListingRow:
    id: str
    jobId: str
    sourceId: str
    externalId: str | None
    sourceUrl: str
    canonicalUrl: str | None
    isPrimary: bool


class FakeJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeJobRow] = {}
        self.listings: FakeListingRepository | None = None  # wired by tests

    async def find_by_content_hash(self, content_hash: str) -> FakeJobRow | None:
        return next((j for j in self.jobs.values() if j.contentHash == content_hash), None)

    async def find_by_canonical_url(self, canonical_url: str) -> FakeJobRow | None:
        return next((j for j in self.jobs.values() if j.canonicalUrl == canonical_url), None)

    async def create_from_normalized(
        self, job: NormalizedJob, *, source_id: str, company_id: str | None
    ) -> FakeJobRow:
        row = FakeJobRow(
            id=uuid.uuid4().hex,
            contentHash=job.contentHash,
            canonicalUrl=job.canonicalUrl,
            companyId=company_id,
        )
        self.jobs[row.id] = row
        assert self.listings is not None
        await self.listings.upsert_listing(
            job_id=row.id,
            source_id=source_id,
            external_id=job.externalId,
            source_url=job.sourceUrl or job.canonicalUrl or "",
            canonical_url=job.canonicalUrl,
            posted_at=job.postedAt,
            raw_data=job.rawData,
            is_primary=True,
        )
        return row


class FakeListingRepository:
    def __init__(self) -> None:
        self.listings: list[FakeListingRow] = []
        self.refreshed: list[str] = []

    async def find_by_source_external_id(
        self, source_id: str, external_id: str
    ) -> FakeListingRow | None:
        return next(
            (
                listing
                for listing in self.listings
                if listing.sourceId == source_id and listing.externalId == external_id
            ),
            None,
        )

    async def upsert_listing(
        self,
        *,
        job_id: str,
        source_id: str,
        external_id: str | None,
        source_url: str,
        canonical_url: str | None,
        posted_at: datetime | None,
        raw_data: dict[str, Any] | None,
        is_primary: bool = False,
    ) -> FakeListingRow:
        if external_id is not None:
            existing = await self.find_by_source_external_id(source_id, external_id)
            if existing is not None:
                existing.sourceUrl = source_url
                existing.canonicalUrl = canonical_url
                return existing
        row = FakeListingRow(
            id=uuid.uuid4().hex,
            jobId=job_id,
            sourceId=source_id,
            externalId=external_id,
            sourceUrl=source_url,
            canonicalUrl=canonical_url,
            isPrimary=is_primary,
        )
        self.listings.append(row)
        return row

    async def refresh_listing(
        self,
        listing_id: str,
        *,
        source_url: str,
        canonical_url: str | None,
        posted_at: datetime | None,
    ) -> FakeListingRow:
        listing = next(x for x in self.listings if x.id == listing_id)
        listing.sourceUrl = source_url
        listing.canonicalUrl = canonical_url
        self.refreshed.append(listing_id)
        return listing


@dataclass
class FakeCompanyRow:
    id: str
    name: str
    normalizedName: str


class FakeCompanyRepository:
    def __init__(self) -> None:
        self.companies: dict[str, FakeCompanyRow] = {}

    async def upsert_by_normalized_name(self, name: str) -> FakeCompanyRow:
        from app.utils.normalization import normalize_company

        normalized = normalize_company(name)
        if normalized not in self.companies:
            self.companies[normalized] = FakeCompanyRow(
                id=uuid.uuid4().hex, name=name.strip(), normalizedName=normalized
            )
        return self.companies[normalized]


@dataclass
class FakeSearchRun:
    id: str
    userId: str | None
    trigger: SearchTrigger
    status: SearchRunStatus
    query: dict[str, Any] | None
    startedAt: datetime | None
    completedAt: datetime | None = None
    sourcesAttempted: list[str] = field(default_factory=list)
    sourcesSucceeded: list[str] = field(default_factory=list)
    sourcesFailed: list[str] = field(default_factory=list)
    jobsFound: int = 0
    jobsNew: int = 0
    jobsDuplicate: int = 0
    errorSummary: str | None = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeSearchRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, FakeSearchRun] = {}

    async def create(
        self,
        *,
        user_id: str | None,
        trigger: SearchTrigger,
        query: dict[str, Any],
        sources_attempted: list[str],
    ) -> FakeSearchRun:
        run = FakeSearchRun(
            id=uuid.uuid4().hex,
            userId=user_id,
            trigger=trigger,
            status=SearchRunStatus.RUNNING,
            query=query,
            startedAt=datetime.now(UTC),
            sourcesAttempted=sources_attempted,
        )
        self.runs[run.id] = run
        return run

    async def finish(self, run_id: str, **kwargs: Any) -> FakeSearchRun:
        run = self.runs[run_id]
        run.status = kwargs["status"]
        run.completedAt = datetime.now(UTC)
        run.sourcesSucceeded = kwargs["sources_succeeded"]
        run.sourcesFailed = kwargs["sources_failed"]
        run.jobsFound = kwargs["jobs_found"]
        run.jobsNew = kwargs["jobs_new"]
        run.jobsDuplicate = kwargs["jobs_duplicate"]
        run.errorSummary = kwargs["error_summary"]
        return run

    async def get_by_id(self, run_id: str) -> FakeSearchRun | None:
        return self.runs.get(run_id)

    async def list_visible_to(
        self, user_id: str, *, limit: int, offset: int
    ) -> tuple[list[FakeSearchRun], int]:
        visible = [r for r in self.runs.values() if r.userId in (None, user_id)]
        visible.sort(key=lambda r: r.createdAt, reverse=True)
        return visible[offset : offset + limit], len(visible)


class StubConnector:
    """Duck-typed connector: yields canned NormalizedJobs, or follows an
    exception script (one entry per search_jobs call)."""

    def __init__(
        self,
        name: str,
        config: JobSourceConfig,
        *,
        jobs: list[NormalizedJob] | None = None,
        script: list[Exception | None] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._name = name
        self.config = config
        self._jobs = jobs or []
        self._script = script or []
        self._delay = delay_seconds
        self.calls = 0

    def get_source_name(self) -> str:
        return self._name

    async def search_jobs(self, params: SourceSearchParams) -> list[RawJob]:
        self.calls += 1
        if self._delay:
            import asyncio

            await asyncio.sleep(self._delay)
        if self._script:
            step = self._script.pop(0)
            if step is not None:
                raise step
        now = datetime.now(UTC)
        return [
            RawJob(
                sourceName=self._name,
                externalId=job.externalId,
                url=job.sourceUrl,
                payload={"i": i},
                fetchedAt=now,
            )
            for i, job in enumerate(self._jobs[: params.limit])
        ]

    def normalize_job(self, raw: RawJob) -> NormalizedJob:
        return self._jobs[raw.payload["i"]]


class FakeRegistry:
    """Implements only what DiscoveryService uses."""

    def __init__(self, connectors: dict[str, StubConnector]) -> None:
        self._connectors = connectors
        self.throttles: dict[str, Any] = {}

    def list_names(self) -> list[str]:
        return sorted(self._connectors)

    def get_config(self, name: str) -> JobSourceConfig:
        return self._connectors[name].config

    def connector_with_config(
        self, name: str, config: JobSourceConfig, throttle: Any = None
    ) -> StubConnector:
        self.throttles[name] = throttle
        connector = self._connectors[name]
        connector.config = config
        return connector


def make_stub_config(name: str, *, enabled: bool = True) -> JobSourceConfig:
    return JobSourceConfig(name=name, displayName=name.title(), enabled=enabled)
