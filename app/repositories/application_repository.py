from app.models import ApplicationStatus
from app.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository):
    """Phase 11 needs only counts for the dashboard; Phase 12 (the tracker)
    adds the CRUD methods."""

    async def count_for_user(
        self, user_id: str, *, status: ApplicationStatus | None = None
    ) -> int:
        where: dict = {"userId": user_id, "deletedAt": None}
        if status is not None:
            where["status"] = status
        return await self._prisma.application.count(where=where)
