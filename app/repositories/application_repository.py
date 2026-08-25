from datetime import datetime
from typing import Any

from app.db.generated.models import Application, ApplicationEvent
from app.models import ApplicationStatus
from app.repositories.base import BaseRepository

_INCLUDE = {
    "job": {
        "include": {
            "listings": {"include": {"source": True}},
            "duplicates": True,
            "analysis": True,
        }
    },
    "events": {"order_by": {"occurredAt": "asc"}},
}


class ApplicationRepository(BaseRepository):
    async def create(
        self, user_id: str, job_id: str, status: ApplicationStatus
    ) -> Application:
        return await self._prisma.application.create(
            data={"userId": user_id, "jobId": job_id, "status": status},  # type: ignore[typeddict-item]
            include=_INCLUDE,  # type: ignore[arg-type]
        )

    async def get_by_user_job(self, user_id: str, job_id: str) -> Application | None:
        return await self._prisma.application.find_first(
            where={"userId": user_id, "jobId": job_id, "deletedAt": None},
            include=_INCLUDE,  # type: ignore[arg-type]
        )

    async def get_for_user(self, application_id: str, user_id: str) -> Application | None:
        row = await self._prisma.application.find_unique(
            where={"id": application_id},
            include=_INCLUDE,  # type: ignore[arg-type]
        )
        if row is None or row.userId != user_id or row.deletedAt is not None:
            return None
        return row

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: ApplicationStatus | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Application], int]:
        where: dict[str, Any] = {"userId": user_id, "deletedAt": None}
        if status is not None:
            where["status"] = status
        rows = await self._prisma.application.find_many(
            where=where,
            order={"updatedAt": "desc"},
            take=limit,
            skip=offset,
            include=_INCLUDE,  # type: ignore[arg-type]
        )
        total = await self._prisma.application.count(where=where)
        return rows, total

    async def update(self, application_id: str, data: dict[str, Any]) -> Application:
        return await self._prisma.application.update(
            where={"id": application_id},
            data=data,  # type: ignore[arg-type]
            include=_INCLUDE,  # type: ignore[arg-type]
        )

    async def add_event(
        self,
        application_id: str,
        *,
        title: str,
        status: ApplicationStatus | None = None,
        notes: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ApplicationEvent:
        data: dict[str, Any] = {
            "applicationId": application_id,
            "title": title,
            "status": status,
            "notes": notes,
        }
        if occurred_at is not None:
            data["occurredAt"] = occurred_at
        return await self._prisma.applicationevent.create(data=data)  # type: ignore[arg-type]

    async def count_by_status(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for status in ApplicationStatus:
            counts[status.value] = await self._prisma.application.count(
                where={"userId": user_id, "deletedAt": None, "status": status}  # type: ignore[typeddict-item]
            )
        return counts

    async def count_for_user(
        self, user_id: str, *, status: ApplicationStatus | None = None
    ) -> int:
        where: dict[str, Any] = {"userId": user_id, "deletedAt": None}
        if status is not None:
            where["status"] = status
        return await self._prisma.application.count(where=where)
