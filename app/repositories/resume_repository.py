from app.db.generated.models import Resume, ResumeVersion
from app.repositories.base import BaseRepository

_VERSION_INCLUDE = {"analysis": True}
_RESUME_INCLUDE = {
    "versions": {"include": _VERSION_INCLUDE, "order_by": {"versionNumber": "desc"}},
}


class ResumeRepository(BaseRepository):
    async def list_for_user(self, user_id: str) -> list[Resume]:
        return await self._prisma.resume.find_many(
            where={"userId": user_id},
            order={"createdAt": "desc"},
            include=_RESUME_INCLUDE,  # type: ignore[arg-type]
        )

    async def get_for_user(self, resume_id: str, user_id: str) -> Resume | None:
        row = await self._prisma.resume.find_unique(
            where={"id": resume_id},
            include=_RESUME_INCLUDE,  # type: ignore[arg-type]
        )
        if row is None or row.userId != user_id:
            return None
        return row

    async def create(self, user_id: str, title: str) -> Resume:
        return await self._prisma.resume.create(
            data={"userId": user_id, "title": title},
            include=_RESUME_INCLUDE,  # type: ignore[arg-type]
        )

    async def delete(self, resume_id: str) -> None:
        await self._prisma.resume.delete(where={"id": resume_id})

    async def create_version(
        self,
        *,
        version_id: str,
        resume_id: str,
        version_number: int,
        file_name: str,
        mime_type: str,
        file_size: int,
        content_hash: str,
        storage_path: str,
        extracted_text: str,
    ) -> ResumeVersion:
        """The id is supplied by the caller: the file is written under that id
        before the row exists, so a failed insert can unlink it."""
        return await self._prisma.resumeversion.create(
            data={
                "id": version_id,
                "resumeId": resume_id,
                "versionNumber": version_number,
                "fileName": file_name,
                "mimeType": mime_type,
                "fileSize": file_size,
                "contentHash": content_hash,
                "storagePath": storage_path,
                "extractedText": extracted_text,
            },
            include=_VERSION_INCLUDE,  # type: ignore[arg-type]
        )

    async def latest_version(self, resume_id: str) -> ResumeVersion | None:
        return await self._prisma.resumeversion.find_first(
            where={"resumeId": resume_id},
            order={"versionNumber": "desc"},
            include=_VERSION_INCLUDE,  # type: ignore[arg-type]
        )

    async def get_version_for_user(self, version_id: str, user_id: str) -> ResumeVersion | None:
        return await self._prisma.resumeversion.find_first(
            where={"id": version_id, "resume": {"is": {"userId": user_id}}},  # type: ignore[typeddict-item]
            include={"analysis": True, "resume": True},  # type: ignore[arg-type]
        )

    async def list_storage_paths(self, resume_id: str) -> list[str]:
        rows = await self._prisma.resumeversion.find_many(where={"resumeId": resume_id})
        return [row.storagePath for row in rows]
