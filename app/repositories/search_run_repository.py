from datetime import UTC, datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.models import SearchRun
from app.models import SearchRunStatus, SearchTrigger
from app.repositories.base import BaseRepository


class SearchRunRepository(BaseRepository):
    async def create(
        self,
        *,
        user_id: str | None,
        trigger: SearchTrigger,
        query: dict[str, Any],
        sources_attempted: list[str],
    ) -> SearchRun:
        return await self._prisma.searchrun.create(
            data={
                "userId": user_id,
                "trigger": trigger,  # type: ignore[typeddict-item]
                "status": SearchRunStatus.RUNNING,  # type: ignore[typeddict-item]
                "query": Json(query),
                "startedAt": datetime.now(UTC),
                "sourcesAttempted": sources_attempted,
            }
        )

    async def finish(
        self,
        run_id: str,
        *,
        status: SearchRunStatus,
        sources_succeeded: list[str],
        sources_failed: list[str],
        jobs_found: int,
        jobs_new: int,
        jobs_duplicate: int,
        error_summary: str | None,
    ) -> SearchRun:
        return await self._prisma.searchrun.update(
            where={"id": run_id},
            data={
                "status": status,  # type: ignore[typeddict-item]
                "completedAt": datetime.now(UTC),
                "sourcesSucceeded": sources_succeeded,
                "sourcesFailed": sources_failed,
                "jobsFound": jobs_found,
                "jobsNew": jobs_new,
                "jobsDuplicate": jobs_duplicate,
                "errorSummary": error_summary,
            },
        )

    async def get_by_id(self, run_id: str) -> SearchRun | None:
        return await self._prisma.searchrun.find_unique(where={"id": run_id})

    async def latest_by_trigger(self, trigger: SearchTrigger) -> SearchRun | None:
        return await self._prisma.searchrun.find_first(
            where={"trigger": trigger},  # type: ignore[typeddict-item]
            order={"createdAt": "desc"},
        )

    async def list_visible_to(
        self, user_id: str, *, limit: int, offset: int
    ) -> tuple[list[SearchRun], int]:
        """A user sees their own runs plus global (scheduled) runs."""
        where = {"OR": [{"userId": user_id}, {"userId": None}]}
        rows = await self._prisma.searchrun.find_many(
            where=where,  # type: ignore[arg-type]
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
        )
        total = await self._prisma.searchrun.count(where=where)  # type: ignore[arg-type]
        return rows, total
