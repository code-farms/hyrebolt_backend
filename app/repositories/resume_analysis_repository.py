from datetime import datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.models import ResumeAnalysis
from app.repositories.base import BaseRepository


class ResumeAnalysisRepository(BaseRepository):
    async def get_by_version_id(self, version_id: str) -> ResumeAnalysis | None:
        return await self._prisma.resumeanalysis.find_unique(where={"versionId": version_id})

    async def upsert_for_version(
        self,
        version_id: str,
        *,
        analysis: dict[str, Any],
        confidence: float | None,
        model: str,
        prompt_version: str,
        input_tokens: int | None,
        output_tokens: int | None,
        processed_at: datetime,
    ) -> ResumeAnalysis:
        data = {
            "analysis": Json(analysis),
            "confidence": confidence,
            "model": model,
            "promptVersion": prompt_version,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "processedAt": processed_at,
        }
        return await self._prisma.resumeanalysis.upsert(
            where={"versionId": version_id},
            data={"create": {"versionId": version_id, **data}, "update": data},  # type: ignore[typeddict-item]
        )
