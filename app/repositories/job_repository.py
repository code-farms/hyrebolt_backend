from app.db.generated.models import Job
from app.repositories.base import BaseRepository


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
