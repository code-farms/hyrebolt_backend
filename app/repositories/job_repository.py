from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.generated import Json
from app.db.generated.models import Job, JobMatch
from app.repositories.base import BaseRepository
from app.sources.models import NormalizedJob


@dataclass(frozen=True)
class JobFilters:
    source: str | None = None
    location: str | None = None
    remote: bool | None = None
    company: str | None = None
    min_salary: int | None = None
    max_experience: float | None = None
    skills: tuple[str, ...] = ()
    date_posted_days: int | None = None


def _job_where(filters: JobFilters) -> dict[str, Any]:
    where: dict[str, Any] = {"deletedAt": None}
    if filters.source:
        where["source"] = {"is": {"name": filters.source}}
    if filters.location:
        where["location"] = {"contains": filters.location, "mode": "insensitive"}
    if filters.remote is not None:
        where["remote"] = filters.remote
    if filters.company:
        where["companyName"] = {"contains": filters.company, "mode": "insensitive"}
    if filters.min_salary is not None:
        where["salaryMax"] = {"gte": filters.min_salary}
    if filters.max_experience is not None:
        where["experienceMin"] = {"lte": filters.max_experience}
    if filters.date_posted_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=filters.date_posted_days)
        where["postedAt"] = {"gte": cutoff}
    for term in filters.skills:
        where.setdefault("AND", []).append(
            {
                "OR": [
                    {"title": {"contains": term, "mode": "insensitive"}},
                    {"description": {"contains": term, "mode": "insensitive"}},
                ]
            }
        )
    return where


def _viewer_include(user_id: str) -> dict[str, Any]:
    return {
        "listings": {"include": {"source": True}},
        "duplicates": True,
        "analysis": True,
        "matches": {"where": {"userId": user_id}},
        "savedBy": {"where": {"userId": user_id}},
    }


class JobRepository(BaseRepository):
    async def get_by_id(self, job_id: str) -> Job | None:
        return await self._prisma.job.find_unique(where={"id": job_id})

    async def list_active(self, *, limit: int = 50, offset: int = 0) -> list[Job]:
        """Non-deleted jobs, newest first. The discovery phases build on this."""
        return await self._prisma.job.find_many(
            where={"deletedAt": None},
            order={"postedAt": "desc"},
            take=limit,
            skip=offset,
        )

    async def find_by_content_hash(self, content_hash: str) -> Job | None:
        return await self._prisma.job.find_first(
            where={"contentHash": content_hash, "deletedAt": None},
            order={"createdAt": "asc"},
        )

    async def find_by_canonical_url(self, canonical_url: str) -> Job | None:
        return await self._prisma.job.find_first(
            where={"canonicalUrl": canonical_url, "deletedAt": None},
            order={"createdAt": "asc"},
        )

    async def find_unanalyzed(self, prompt_version: str, *, limit: int) -> list[Job]:
        """Jobs with no analysis, or one from an older prompt version."""
        return await self._prisma.job.find_many(
            where={
                "deletedAt": None,
                "OR": [
                    {"analysis": None},
                    {"analysis": {"isNot": {"promptVersion": prompt_version}}},
                ],
            },
            order={"createdAt": "desc"},
            take=limit,
        )

    async def find_candidates_by_company(self, company_id: str, *, limit: int) -> list[Job]:
        """Fuzzy-dedup blocking: same company (spec signal 3), newest first."""
        return await self._prisma.job.find_many(
            where={"companyId": company_id, "deletedAt": None},
            order={"createdAt": "desc"},
            take=limit,
        )

    async def get_with_listings(self, job_id: str) -> Job | None:
        return await self._prisma.job.find_unique(
            where={"id": job_id},
            include={
                "listings": {"include": {"source": True}},
                "duplicates": True,
                "analysis": True,
            },
        )

    async def count_created_since(self, since: datetime) -> int:
        return await self._prisma.job.count(
            where={"createdAt": {"gte": since}, "deletedAt": None}
        )

    async def list_filtered(
        self, user_id: str, filters: JobFilters, *, limit: int, offset: int
    ) -> tuple[list[Job], int]:
        """Newest-first job listing with the viewer's match + saved context."""
        where = _job_where(filters)
        rows = await self._prisma.job.find_many(
            where=where,  # type: ignore[arg-type]
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
            include=_viewer_include(user_id),  # type: ignore[arg-type]
        )
        total = await self._prisma.job.count(where=where)  # type: ignore[arg-type]
        return rows, total

    async def list_by_score(
        self,
        user_id: str,
        filters: JobFilters,
        *,
        min_score: float,
        limit: int,
        offset: int,
    ) -> tuple[list[JobMatch], int]:
        """Score-ordered listing: prisma can't order jobs by a relation
        aggregate, so query the matches directly and include the job."""
        where: dict[str, Any] = {
            "userId": user_id,
            "overallScore": {"gte": min_score},
            "job": {"is": _job_where(filters)},
        }
        rows = await self._prisma.jobmatch.find_many(
            where=where,  # type: ignore[arg-type]
            order={"overallScore": "desc"},
            take=limit,
            skip=offset,
            include={"job": {"include": _viewer_include(user_id)}},  # type: ignore[arg-type]
        )
        total = await self._prisma.jobmatch.count(where=where)  # type: ignore[arg-type]
        return rows, total

    async def list_active_with_listings(
        self, *, limit: int, offset: int
    ) -> tuple[list[Job], int]:
        where = {"deletedAt": None}
        rows = await self._prisma.job.find_many(
            where=where,  # type: ignore[arg-type]
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
            include={
                "listings": {"include": {"source": True}},
                "duplicates": True,
                "analysis": True,
            },
        )
        total = await self._prisma.job.count(where=where)  # type: ignore[arg-type]
        return rows, total

    async def create_from_normalized(
        self,
        job: NormalizedJob,
        *,
        source_id: str,
        company_id: str | None,
        duplicate_of_id: str | None = None,
    ) -> Job:
        """Creates the Job and its isPrimary listing atomically — a Job must
        never exist without its primary listing."""
        data: dict[str, Any] = {
            "externalId": job.externalId,
            "sourceId": source_id,
            "sourceUrl": job.sourceUrl,
            "canonicalUrl": job.canonicalUrl,
            "title": job.title,
            "normalizedTitle": job.normalizedTitle,
            "description": job.description,
            "companyId": company_id,
            "companyName": job.companyName,
            "location": job.location,
            "normalizedLocation": job.normalizedLocation,
            "country": job.country,
            "remote": job.remote,
            "hybrid": job.hybrid,
            "employmentType": job.employmentType,
            "experienceMin": job.experienceMin,
            "experienceMax": job.experienceMax,
            "salaryMin": job.salaryMin,
            "salaryMax": job.salaryMax,
            "salaryCurrency": job.salaryCurrency,
            "postedAt": job.postedAt,
            "rawData": Json(job.rawData) if job.rawData is not None else None,
            "contentHash": job.contentHash,
            "duplicateOfId": duplicate_of_id,
        }
        async with self._prisma.tx() as tx:
            created = await tx.job.create(data=data)  # type: ignore[arg-type]
            await tx.jobsourcelisting.create(
                data={
                    "jobId": created.id,
                    "sourceId": source_id,
                    "externalId": job.externalId,
                    "sourceUrl": job.sourceUrl or job.canonicalUrl or "",
                    "canonicalUrl": job.canonicalUrl,
                    "postedAt": job.postedAt,
                    "isPrimary": True,
                    "rawData": Json(job.rawData) if job.rawData is not None else None,
                }
            )
        return created
