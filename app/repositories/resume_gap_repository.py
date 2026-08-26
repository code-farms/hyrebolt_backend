from datetime import datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.models import ResumeGapAnalysis
from app.repositories.base import BaseRepository


class ResumeGapRepository(BaseRepository):
    async def get(self, version_id: str, job_id: str) -> ResumeGapAnalysis | None:
        return await self._prisma.resumegapanalysis.find_unique(
            where={"versionId_jobId": {"versionId": version_id, "jobId": job_id}}
        )

    async def upsert(
        self,
        version_id: str,
        job_id: str,
        *,
        analysis: dict[str, Any],
        model: str | None,
        prompt_version: str,
        processed_at: datetime,
    ) -> ResumeGapAnalysis:
        data = {
            "analysis": Json(analysis),
            "model": model,
            "promptVersion": prompt_version,
            "processedAt": processed_at,
        }
        return await self._prisma.resumegapanalysis.upsert(
            where={"versionId_jobId": {"versionId": version_id, "jobId": job_id}},
            data={"create": {"versionId": version_id, "jobId": job_id, **data}, "update": data},  # type: ignore[typeddict-item]
        )
