"""In-memory fakes for the Phase 13 company/watchlist slice."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.models import WatchlistPriority
from app.services.company_service import CompanyService
from app.sources.models import CompanyMetadata
from app.utils.normalization import normalize_company
from tests.discovery.test_jobs_api import make_job_row


@dataclass
class FakeCompany:
    id: str
    name: str
    normalizedName: str
    website: str | None = None
    careersUrl: str | None = None
    industry: str | None = None
    stage: str | None = None
    location: str | None = None
    description: str | None = None
    logoUrl: str | None = None
    metadataSource: str | None = None
    watchlistEntries: list[Any] = field(default_factory=list)
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeEntry:
    id: str
    userId: str
    companyId: str
    priority: WatchlistPriority = WatchlistPriority.MEDIUM
    preferredRoles: list[str] = field(default_factory=list)
    excludedRoles: list[str] = field(default_factory=list)
    notes: str | None = None
    company: FakeCompany | None = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))
    updatedAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeWatchlistRepository:
    def __init__(self, companies: "FakeCompanyRepository") -> None:
        self.rows: dict[str, FakeEntry] = {}
        self._companies = companies

    def _attach(self, row: FakeEntry) -> FakeEntry:
        row.company = self._companies.companies.get(row.companyId)
        return row

    async def list_for_user(self, user_id: str) -> list[FakeEntry]:
        return [self._attach(r) for r in self.rows.values() if r.userId == user_id]

    async def get_for_user(self, entry_id: str, user_id: str) -> FakeEntry | None:
        row = self.rows.get(entry_id)
        if row is None or row.userId != user_id:
            return None
        return self._attach(row)

    async def get_by_user_company(self, user_id: str, company_id: str) -> FakeEntry | None:
        row = next(
            (r for r in self.rows.values() if r.userId == user_id and r.companyId == company_id),
            None,
        )
        return self._attach(row) if row else None

    async def create(self, user_id: str, company_id: str, data: dict[str, Any]) -> FakeEntry:
        row = FakeEntry(id=uuid.uuid4().hex, userId=user_id, companyId=company_id, **data)
        self.rows[row.id] = row
        return self._attach(row)

    async def update(self, entry_id: str, data: dict[str, Any]) -> FakeEntry:
        row = self.rows[entry_id]
        for key, value in data.items():
            setattr(row, key, value)
        row.updatedAt = datetime.now(UTC)
        return self._attach(row)

    async def delete(self, entry_id: str) -> None:
        self.rows.pop(entry_id, None)

    async def list_all_preferred_roles(self) -> list[str]:
        return list(dict.fromkeys(role for r in self.rows.values() for role in r.preferredRoles))


class FakeCompanyRepository:
    def __init__(self) -> None:
        self.companies: dict[str, FakeCompany] = {}
        self.watchlists: FakeWatchlistRepository | None = None

    def seed(self, name: str, **metadata: Any) -> FakeCompany:
        row = FakeCompany(
            id=uuid.uuid4().hex, name=name, normalizedName=normalize_company(name), **metadata
        )
        self.companies[row.id] = row
        return row

    def _with_viewer(self, row: FakeCompany, viewer_id: str | None) -> FakeCompany:
        if viewer_id is not None and self.watchlists is not None:
            row.watchlistEntries = [
                e
                for e in self.watchlists.rows.values()
                if e.userId == viewer_id and e.companyId == row.id
            ]
        return row

    async def upsert_by_normalized_name(
        self, name: str, metadata: CompanyMetadata | None = None
    ) -> FakeCompany:
        normalized = normalize_company(name)
        row = next((c for c in self.companies.values() if c.normalizedName == normalized), None)
        if row is None:
            row = self.seed(name.strip())
        if metadata is not None:
            for key, value in metadata.model_dump(exclude_none=True).items():
                if getattr(row, key) is None:
                    setattr(row, key, value)
        return row

    async def get_by_id(self, company_id: str, *, viewer_id: str | None = None):
        row = self.companies.get(company_id)
        return self._with_viewer(row, viewer_id) if row else None

    async def search(self, query: str | None, *, viewer_id: str, limit: int, offset: int):
        rows = sorted(self.companies.values(), key=lambda c: c.name.casefold())
        if query:
            rows = [c for c in rows if query.casefold() in c.name.casefold()]
        return [self._with_viewer(r, viewer_id) for r in rows[offset : offset + limit]], len(rows)

    async def update_metadata(self, company_id: str, data: dict[str, Any]) -> FakeCompany:
        row = self.companies[company_id]
        for key, value in data.items():
            setattr(row, key, value)
        return row

    async def list_watched_careers_urls(self, *, limit: int = 200) -> list[tuple[str, str]]:
        watched = {e.companyId for e in (self.watchlists.rows.values() if self.watchlists else [])}
        return [
            (c.name, c.careersUrl)
            for c in self.companies.values()
            if c.id in watched and c.careersUrl
        ][:limit]


class FakeJobsForCompanies:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def add(self, job_id: str, company_id: str, **kwargs: Any) -> Any:
        row = make_job_row(job_id, **kwargs)
        row.companyId = company_id
        self.jobs.append(row)
        return row

    def _open(self, company_ids: list[str]) -> list[Any]:
        return [j for j in self.jobs if j.companyId in company_ids and j.deletedAt is None]

    async def list_by_companies(self, user_id: str, company_ids: list[str], *, limit: int, offset: int):
        rows = self._open(company_ids)
        return rows[offset : offset + limit], len(rows)

    async def count_open_by_company(self, company_ids: list[str]) -> dict[str, int]:
        return {cid: len(self._open([cid])) for cid in company_ids}

    async def find_candidates_by_company(self, company_id: str, *, limit: int):
        return self._open([company_id])[:limit]


class RecordingMatches:
    def __init__(self) -> None:
        self.stale_calls: list[tuple[str, str, str]] = []

    async def mark_stale_for_company(self, user_id: str, company_id: str, company_name: str) -> int:
        self.stale_calls.append((user_id, company_id, company_name))
        return 2


class RecordingMatching:
    def __init__(self) -> None:
        self.rescored: list[tuple[str, str, int]] = []

    async def rescore_company(self, user, company_id: str, *, limit: int) -> int:
        self.rescored.append((user.id, company_id, limit))
        return 1


@dataclass
class CompanyHarness:
    service: CompanyService
    companies: FakeCompanyRepository
    watchlists: FakeWatchlistRepository
    jobs: FakeJobsForCompanies
    matches: RecordingMatches
    matching: RecordingMatching


def make_harness() -> CompanyHarness:
    companies = FakeCompanyRepository()
    watchlists = FakeWatchlistRepository(companies)
    companies.watchlists = watchlists
    jobs = FakeJobsForCompanies()
    matches = RecordingMatches()
    matching = RecordingMatching()
    service = CompanyService(
        companies=companies,  # type: ignore[arg-type]
        watchlists=watchlists,  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        matches=matches,  # type: ignore[arg-type]
        matching=matching,  # type: ignore[arg-type]
        settings=get_settings(),
    )
    return CompanyHarness(service, companies, watchlists, jobs, matches, matching)
