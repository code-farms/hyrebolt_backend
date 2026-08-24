from datetime import datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.models import JobSourceListing
from app.repositories.base import BaseRepository


class JobSourceListingRepository(BaseRepository):
    async def find_by_source_external_id(
        self, source_id: str, external_id: str
    ) -> JobSourceListing | None:
        return await self._prisma.jobsourcelisting.find_unique(
            where={"sourceId_externalId": {"sourceId": source_id, "externalId": external_id}}
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
    ) -> JobSourceListing:
        create_data: dict[str, Any] = {
            "jobId": job_id,
            "sourceId": source_id,
            "externalId": external_id,
            "sourceUrl": source_url,
            "canonicalUrl": canonical_url,
            "postedAt": posted_at,
            "isPrimary": is_primary,
            "rawData": Json(raw_data) if raw_data is not None else None,
        }
        if external_id is not None:
            return await self._prisma.jobsourcelisting.upsert(
                where={
                    "sourceId_externalId": {"sourceId": source_id, "externalId": external_id}
                },
                data={
                    "create": create_data,
                    "update": {
                        "sourceUrl": source_url,
                        "canonicalUrl": canonical_url,
                        "postedAt": posted_at,
                    },
                },
            )
        # No externalId: the compound unique treats NULLs as distinct, so
        # match on (jobId, sourceId, canonicalUrl) manually.
        existing = await self._prisma.jobsourcelisting.find_first(
            where={"jobId": job_id, "sourceId": source_id, "canonicalUrl": canonical_url}
        )
        if existing is not None:
            return await self._prisma.jobsourcelisting.update(
                where={"id": existing.id},
                data={"sourceUrl": source_url, "postedAt": posted_at},
            )
        return await self._prisma.jobsourcelisting.create(data=create_data)

    async def refresh_listing(
        self,
        listing_id: str,
        *,
        source_url: str,
        canonical_url: str | None,
        posted_at: datetime | None,
    ) -> JobSourceListing:
        return await self._prisma.jobsourcelisting.update(
            where={"id": listing_id},
            data={
                "sourceUrl": source_url,
                "canonicalUrl": canonical_url,
                "postedAt": posted_at,
            },
        )
