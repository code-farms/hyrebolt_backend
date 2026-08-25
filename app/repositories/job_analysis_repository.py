from datetime import datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.models import JobAnalysis
from app.repositories.base import BaseRepository


class JobAnalysisRepository(BaseRepository):
    async def get_by_job_id(self, job_id: str) -> JobAnalysis | None:
        return await self._prisma.jobanalysis.find_unique(where={"jobId": job_id})

    async def upsert_for_job(
        self,
        job_id: str,
        *,
        analysis: dict[str, Any],
        confidence: float | None,
        model: str,
        prompt_version: str,
        input_tokens: int | None,
        output_tokens: int | None,
        processed_at: datetime,
    ) -> JobAnalysis:
        data = {
            "analysis": Json(analysis),
            "confidence": confidence,
            "model": model,
            "promptVersion": prompt_version,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "processedAt": processed_at,
        }
        return await self._prisma.jobanalysis.upsert(
            where={"jobId": job_id},
            data={"create": {"jobId": job_id, **data}, "update": data},  # type: ignore[typeddict-item]
        )
