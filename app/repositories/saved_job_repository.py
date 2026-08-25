from app.db.generated.models import SavedJob
from app.repositories.base import BaseRepository

_JOB_INCLUDE = {
    "job": {
        "include": {
            "listings": {"include": {"source": True}},
            "duplicates": True,
            "analysis": True,
        }
    }
}


class SavedJobRepository(BaseRepository):
    async def save(self, user_id: str, job_id: str) -> SavedJob:
        return await self._prisma.savedjob.upsert(
            where={"userId_jobId": {"userId": user_id, "jobId": job_id}},
            data={"create": {"userId": user_id, "jobId": job_id}, "update": {}},
        )

    async def is_saved(self, user_id: str, job_id: str) -> bool:
        row = await self._prisma.savedjob.find_unique(
            where={"userId_jobId": {"userId": user_id, "jobId": job_id}}
        )
        return row is not None

    async def unsave(self, user_id: str, job_id: str) -> int:
        return await self._prisma.savedjob.delete_many(
            where={"userId": user_id, "jobId": job_id}
        )

    async def list_for_user(
        self, user_id: str, *, limit: int, offset: int
    ) -> tuple[list[SavedJob], int]:
        where = {"userId": user_id, "job": {"is": {"deletedAt": None}}}
        rows = await self._prisma.savedjob.find_many(
            where=where,  # type: ignore[arg-type]
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
            include=_JOB_INCLUDE,  # type: ignore[arg-type]
        )
        total = await self._prisma.savedjob.count(where=where)  # type: ignore[arg-type]
        return rows, total

    async def count_for_user(self, user_id: str) -> int:
        return await self._prisma.savedjob.count(
            where={"userId": user_id, "job": {"is": {"deletedAt": None}}}
        )
