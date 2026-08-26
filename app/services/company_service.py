"""Phase 13: company watchlist + startup metadata.

Companies are shared rows (resolved by dedup from job postings); watchlist
entries are per user. Metadata edits are allowed only for companies the user
watches, and always stamp metadataSource="user" so provenance stays honest."""

from typing import Any

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.generated.models import Company, CompanyWatchlist, Job, User
from app.repositories import (
    CompanyRepository,
    CompanyWatchlistRepository,
    JobMatchRepository,
    JobRepository,
)
from app.schemas.company import (
    METADATA_SOURCE_USER,
    CompanyListOut,
    CompanyOut,
    WatchlistCreateIn,
    WatchlistEntryOut,
    WatchlistListOut,
    company_out,
    watchlist_entry_out,
)
from app.services.candidate_matching_service import CandidateMatchingService
from app.sources.models import CompanyMetadata

logger = get_logger(__name__)


class CompanyService:
    def __init__(
        self,
        companies: CompanyRepository,
        watchlists: CompanyWatchlistRepository,
        jobs: JobRepository,
        matches: JobMatchRepository,
        matching: CandidateMatchingService,
        settings: Settings,
    ) -> None:
        self._companies = companies
        self._watchlists = watchlists
        self._jobs = jobs
        self._matches = matches
        self._matching = matching
        self._settings = settings

    # ── companies ──────────────────────────────────────────────────────

    async def list_companies(
        self, user: User, *, query: str | None, limit: int, offset: int
    ) -> CompanyListOut:
        rows, total = await self._companies.search(
            query, viewer_id=user.id, limit=limit, offset=offset
        )
        counts = await self._jobs.count_open_by_company([row.id for row in rows])
        return CompanyListOut(
            items=[company_out(row, open_positions=counts.get(row.id, 0)) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_company(self, user: User, company_id: str) -> CompanyOut:
        company = await self._require_company(company_id, viewer_id=user.id)
        counts = await self._jobs.count_open_by_company([company.id])
        return company_out(company, open_positions=counts.get(company.id, 0))

    async def list_company_jobs(
        self, user: User, company_id: str, *, limit: int, offset: int
    ) -> tuple[list[Job], int]:
        company = await self._require_company(company_id)
        return await self._jobs.list_by_companies(
            user.id, [company.id], limit=limit, offset=offset
        )

    async def update_metadata(
        self, user: User, company_id: str, data: dict[str, Any]
    ) -> CompanyOut:
        company = await self._require_company(company_id)
        entry = await self._watchlists.get_by_user_company(user.id, company.id)
        if entry is None:
            # Metadata is shared: only someone watching the company may edit it.
            raise NotFoundError("Company not found.")
        if data:
            company = await self._companies.update_metadata(
                company.id, {**data, "metadataSource": METADATA_SOURCE_USER}
            )
            logger.info("company_metadata_updated", company_id=company.id, fields=sorted(data))
        counts = await self._jobs.count_open_by_company([company.id])
        return company_out(company, open_positions=counts.get(company.id, 0), entry=entry)

    # ── watchlist ──────────────────────────────────────────────────────

    async def list_watchlist(self, user: User) -> WatchlistListOut:
        rows = await self._watchlists.list_for_user(user.id)
        counts = await self._jobs.count_open_by_company([row.companyId for row in rows])
        return WatchlistListOut(
            items=[
                watchlist_entry_out(row, open_positions=counts.get(row.companyId, 0))
                for row in rows
            ],
            total=len(rows),
        )

    async def recent_watchlist_jobs(
        self, user: User, *, limit: int, offset: int
    ) -> tuple[list[Job], int]:
        rows = await self._watchlists.list_for_user(user.id)
        return await self._jobs.list_by_companies(
            user.id, [row.companyId for row in rows], limit=limit, offset=offset
        )

    async def add_to_watchlist(self, user: User, payload: WatchlistCreateIn) -> WatchlistEntryOut:
        company = await self._resolve_company(payload)
        if await self._watchlists.get_by_user_company(user.id, company.id) is not None:
            raise ConflictError("Company is already on your watchlist.")
        entry = await self._watchlists.create(
            user.id,
            company.id,
            {
                "priority": payload.priority,
                "preferredRoles": payload.preferredRoles,
                "excludedRoles": payload.excludedRoles,
                "notes": payload.notes,
            },
        )
        logger.info("watchlist_added", user_id=user.id, company_id=company.id)
        await self._after_change(user, company)
        return await self._entry_out(entry)

    async def update_entry(
        self, user: User, entry_id: str, data: dict[str, Any]
    ) -> WatchlistEntryOut:
        entry = await self._require_entry(user, entry_id)
        if data:
            entry = await self._watchlists.update(entry.id, data)
            assert entry.company is not None
            await self._after_change(user, entry.company)
        return await self._entry_out(entry)

    async def remove_entry(self, user: User, entry_id: str) -> None:
        entry = await self._require_entry(user, entry_id)
        await self._watchlists.delete(entry.id)
        logger.info("watchlist_removed", user_id=user.id, company_id=entry.companyId)
        assert entry.company is not None
        await self._after_change(user, entry.company)

    # ── internals ──────────────────────────────────────────────────────

    async def _resolve_company(self, payload: WatchlistCreateIn) -> Company:
        if payload.companyId:
            return await self._require_company(payload.companyId)
        assert payload.companyName is not None
        metadata = (
            CompanyMetadata(
                careersUrl=payload.careersUrl,
                website=payload.website,
                metadataSource=METADATA_SOURCE_USER,
            )
            if payload.careersUrl or payload.website
            else None
        )
        return await self._companies.upsert_by_normalized_name(payload.companyName, metadata)

    async def _require_company(
        self, company_id: str, *, viewer_id: str | None = None
    ) -> Company:
        company = await self._companies.get_by_id(company_id, viewer_id=viewer_id)
        if company is None:
            raise NotFoundError("Company not found.")
        return company

    async def _require_entry(self, user: User, entry_id: str) -> CompanyWatchlist:
        entry = await self._watchlists.get_for_user(entry_id, user.id)
        if entry is None:
            raise NotFoundError("Watchlist entry not found.")
        return entry

    async def _entry_out(self, entry: CompanyWatchlist) -> WatchlistEntryOut:
        counts = await self._jobs.count_open_by_company([entry.companyId])
        return watchlist_entry_out(entry, open_positions=counts.get(entry.companyId, 0))

    async def _after_change(self, user: User, company: Company) -> None:
        """Watchlist edits change this user's scores for the company: mark
        every stored match stale (the nightly batch re-scores whatever the
        bounded inline pass below doesn't reach). Profile preferred-company
        edits don't do this yet — unifying the two is a follow-up."""
        stale = await self._matches.mark_stale_for_company(user.id, company.id, company.name)
        rescored = await self._matching.rescore_company(
            user, company.id, limit=self._settings.match_batch_limit
        )
        logger.info(
            "watchlist_rescored",
            user_id=user.id,
            company_id=company.id,
            stale=stale,
            rescored=rescored,
        )
