"""Phase 5 deduplication: EXACT signals only — source external id, contentHash,
canonicalUrl. Phase 6 layers similarity scoring and duplicateOf links on top
of the "else new" branch without changing this decision order."""

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.repositories import (
    CompanyRepository,
    JobRepository,
    JobSourceListingRepository,
    JobSourceRepository,
)
from app.sources.models import NormalizedJob

logger = get_logger(__name__)


@dataclass
class BatchPersistResult:
    found: int = 0
    new: int = 0
    duplicate: int = 0
    new_job_ids: list[str] = field(default_factory=list)


class DeduplicationService:
    def __init__(
        self,
        jobs: JobRepository,
        listings: JobSourceListingRepository,
        companies: CompanyRepository,
        sources: JobSourceRepository,
    ) -> None:
        self._jobs = jobs
        self._listings = listings
        self._companies = companies
        self._sources = sources

    async def persist_batch(self, jobs: list[NormalizedJob]) -> BatchPersistResult:
        """Sequential on purpose: within one run, a later occurrence of the
        same job (cross-source) must see the earlier one's committed rows."""
        result = BatchPersistResult()
        source_ids: dict[str, str] = {}
        for job in jobs:
            source_id = await self._resolve_source_id(job.sourceName, source_ids)
            if source_id is None:
                logger.warning("job_persist_skipped_unknown_source", source=job.sourceName)
                continue
            result.found += 1
            new_job_id = await self._persist_one(job, source_id)
            if new_job_id is not None:
                result.new += 1
                result.new_job_ids.append(new_job_id)
            else:
                result.duplicate += 1
        return result

    async def _persist_one(self, job: NormalizedJob, source_id: str) -> str | None:
        """Returns the created Job id for a NEW job, None for a duplicate."""
        source_url = job.sourceUrl or job.canonicalUrl or ""
        if not source_url:
            logger.warning(
                "job_listing_missing_url", source=job.sourceName, external_id=job.externalId
            )

        # (a) Same source + external id: seen before, refresh the listing.
        if job.externalId is not None:
            listing = await self._listings.find_by_source_external_id(source_id, job.externalId)
            if listing is not None:
                await self._listings.refresh_listing(
                    listing.id,
                    source_url=source_url,
                    canonical_url=job.canonicalUrl,
                    posted_at=job.postedAt,
                )
                return None

        # (b) Exact content hash / (c) exact canonical URL: same job from
        # another source — record the extra listing, never mutate the Job.
        existing = await self._jobs.find_by_content_hash(job.contentHash)
        if existing is None and job.canonicalUrl is not None:
            existing = await self._jobs.find_by_canonical_url(job.canonicalUrl)
        if existing is not None:
            await self._listings.upsert_listing(
                job_id=existing.id,
                source_id=source_id,
                external_id=job.externalId,
                source_url=source_url,
                canonical_url=job.canonicalUrl,
                posted_at=job.postedAt,
                raw_data=job.rawData,
                is_primary=False,
            )
            return None

        # (d) New job.
        company = await self._companies.upsert_by_normalized_name(job.companyName)
        created = await self._jobs.create_from_normalized(
            job, source_id=source_id, company_id=company.id
        )
        return created.id

    async def _resolve_source_id(
        self, source_name: str, cache: dict[str, str]
    ) -> str | None:
        if source_name not in cache:
            row = await self._sources.get_by_name(source_name)
            if row is None:
                return None
            cache[source_name] = row.id
        return cache[source_name]
