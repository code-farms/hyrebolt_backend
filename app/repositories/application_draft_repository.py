from datetime import datetime
from typing import Any

from app.db.generated.models import ApplicationDraft
from app.models import ApplicationDraftKind
from app.repositories.base import BaseRepository


def _key(user_id: str, job_id: str, kind: ApplicationDraftKind) -> dict[str, Any]:
    return {"userId_jobId_kind": {"userId": user_id, "jobId": job_id, "kind": kind}}


class ApplicationDraftRepository(BaseRepository):
    async def list_for_job(self, user_id: str, job_id: str) -> list[ApplicationDraft]:
        return await self._prisma.applicationdraft.find_many(
            where={"userId": user_id, "jobId": job_id}
        )

    async def get(
        self, user_id: str, job_id: str, kind: ApplicationDraftKind
    ) -> ApplicationDraft | None:
        return await self._prisma.applicationdraft.find_unique(where=_key(user_id, job_id, kind))  # type: ignore[arg-type]

    async def upsert_generated(
        self,
        user_id: str,
        job_id: str,
        kind: ApplicationDraftKind,
        *,
        content: str,
        resume_version_id: str | None,
        prompt_version: str,
        model: str,
        generated_at: datetime,
    ) -> ApplicationDraft:
        """A (re)generation replaces the visible text and clears any edit."""
        data: dict[str, Any] = {
            "content": content,
            "generatedContent": content,
            "resumeVersionId": resume_version_id,
            "promptVersion": prompt_version,
            "model": model,
            "generatedAt": generated_at,
            "editedAt": None,
        }
        return await self._prisma.applicationdraft.upsert(
            where=_key(user_id, job_id, kind),  # type: ignore[arg-type]
            data={
                "create": {"userId": user_id, "jobId": job_id, "kind": kind, **data},
                "update": data,
            },  # type: ignore[typeddict-item]
        )

    async def upsert_content(
        self,
        user_id: str,
        job_id: str,
        kind: ApplicationDraftKind,
        *,
        content: str,
        edited_at: datetime,
    ) -> ApplicationDraft:
        """A save keeps the generation provenance; a save with no prior draft
        creates a hand-written one (generatedContent stays null)."""
        return await self._prisma.applicationdraft.upsert(
            where=_key(user_id, job_id, kind),  # type: ignore[arg-type]
            data={
                "create": {
                    "userId": user_id,
                    "jobId": job_id,
                    "kind": kind,
                    "content": content,
                    "editedAt": edited_at,
                },
                "update": {"content": content, "editedAt": edited_at},
            },  # type: ignore[typeddict-item]
        )
