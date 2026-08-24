from typing import Any

from app.db.generated import Json
from app.db.generated.models import Job
from app.repositories.base import BaseRepository
from app.sources.models import NormalizedJob


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

    async def create_from_normalized(
        self, job: NormalizedJob, *, source_id: str, company_id: str | None
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
