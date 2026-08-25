from datetime import UTC, datetime
from typing import Any

from app.db.generated.models import JobMatch
from app.models import MatchFeedback
from app.repositories.base import BaseRepository


class JobMatchRepository(BaseRepository):
    async def get_by_user_job(self, user_id: str, job_id: str) -> JobMatch | None:
        return await self._prisma.jobmatch.find_unique(
            where={"userId_jobId": {"userId": user_id, "jobId": job_id}}
        )

    async def upsert_for_user_job(
        self, user_id: str, job_id: str, data: dict[str, Any]
    ) -> JobMatch:
        """`data` carries scores/AI/provenance fields. Feedback fields are
        deliberately never included: a re-score must not erase user feedback."""
        return await self._prisma.jobmatch.upsert(
            where={"userId_jobId": {"userId": user_id, "jobId": job_id}},
            data={
                "create": {"userId": user_id, "jobId": job_id, **data},
                "update": data,
            },
        )

    async def set_feedback(
        self, match_id: str, feedback: MatchFeedback
    ) -> JobMatch:
        return await self._prisma.jobmatch.update(
            where={"id": match_id},
            data={"feedback": feedback, "feedbackAt": datetime.now(UTC)},  # type: ignore[typeddict-item]
        )

    async def list_ranked_for_user(
        self, user_id: str, *, limit: int, offset: int, min_score: float
    ) -> tuple[list[JobMatch], int]:
        where: dict[str, Any] = {
            "userId": user_id,
            "overallScore": {"gte": min_score},
            "job": {"is": {"deletedAt": None}},
            # The one Phase 8 personalization rule: hide what the user said
            # is not relevant. Phase 16 layers richer signals.
            "OR": [{"feedback": None}, {"feedback": {"not": MatchFeedback.NOT_RELEVANT}}],
        }
        rows = await self._prisma.jobmatch.find_many(
            where=where,
            order={"overallScore": "desc"},
            take=limit,
            skip=offset,
            include={
                "job": {
                    "include": {
                        "listings": {"include": {"source": True}},
                        "duplicates": True,
                        "analysis": True,
                    }
                }
            },
        )
        total = await self._prisma.jobmatch.count(where=where)
        return rows, total

    async def count_in_score_band(
        self, user_id: str, *, min_score: float, max_score: float | None = None
    ) -> int:
        score: dict[str, float] = {"gte": min_score}
        if max_score is not None:
            score["lt"] = max_score
        return await self._prisma.jobmatch.count(
            where={
                "userId": user_id,
                "overallScore": score,
                "job": {"is": {"deletedAt": None}},
            }
        )

    async def count_updated_since(self, since: datetime) -> int:
        return await self._prisma.jobmatch.count(where={"updatedAt": {"gte": since}})

    async def find_unmatched_job_ids(
        self, user_id: str, scoring_version: str, *, limit: int
    ) -> list[str]:
        """Active jobs with no current-version match for this user."""
        jobs = await self._prisma.job.find_many(
            where={
                "deletedAt": None,
                "OR": [
                    {"matches": {"none": {"userId": user_id}}},
                    {
                        "matches": {
                            "some": {
                                "userId": user_id,
                                "scoringVersion": {"not": scoring_version},
                            }
                        }
                    },
                ],
            },
            order={"createdAt": "desc"},
            take=limit,
        )
        return [job.id for job in jobs]
