"""Resume upload, versions and selection (Phase 14).

Upload = validate + extract text + persist. It never calls the LLM: analysis
is its own endpoint so a slow or failing provider can't lose a file. The
original is written under a pre-generated version id before the row exists,
so a failed insert can unlink it."""

import hashlib
import uuid
from pathlib import Path, PurePosixPath

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.generated.errors import UniqueViolationError
from app.db.generated.models import Resume, ResumeVersion, User
from app.repositories import ProfileRepository, ResumeRepository
from app.schemas.resume import ResumeListOut, ResumeOut, resume_out
from app.services.resume_storage import ResumeStorage
from app.services.resume_text_extractor import MIME_TYPES, extract_text, sniff_kind

logger = get_logger(__name__)


class ResumeService:
    def __init__(
        self,
        resumes: ResumeRepository,
        profiles: ProfileRepository,
        storage: ResumeStorage,
        settings: Settings,
    ) -> None:
        self._resumes = resumes
        self._profiles = profiles
        self._storage = storage
        self._settings = settings

    async def list(self, user: User) -> ResumeListOut:
        selected = await self._selected_id(user)
        rows = await self._resumes.list_for_user(user.id)
        return ResumeListOut(
            items=[resume_out(row, selected_resume_id=selected) for row in rows],
            total=len(rows),
            selectedResumeId=selected,
        )

    async def get(self, user: User, resume_id: str) -> ResumeOut:
        resume = await self._require(user, resume_id)
        return resume_out(resume, selected_resume_id=await self._selected_id(user))

    async def upload(
        self,
        user: User,
        *,
        filename: str,
        data: bytes,
        title: str | None,
        resume_id: str | None,
    ) -> ResumeOut:
        kind = sniff_kind(filename, data[:1024])
        text = await extract_text(
            data,
            kind,
            max_chars=self._settings.resume_max_text_chars,
            timeout_seconds=self._settings.resume_extract_timeout_seconds,
        )
        content_hash = hashlib.sha256(data).hexdigest()

        if resume_id is not None:
            resume = await self._require(user, resume_id)
            latest = await self._resumes.latest_version(resume.id)
            if latest is not None and latest.contentHash == content_hash:
                raise ConflictError("This file is identical to the current version.")
            version_number = (latest.versionNumber if latest else 0) + 1
        else:
            resume = await self._resumes.create(user.id, title or _default_title(filename))
            version_number = 1

        version_id = uuid.uuid4().hex
        storage_path = await self._storage.save(user.id, version_id, kind, data)
        try:
            await self._resumes.create_version(
                version_id=version_id,
                resume_id=resume.id,
                version_number=version_number,
                file_name=_safe_filename(filename, kind),
                mime_type=MIME_TYPES[kind],
                file_size=len(data),
                content_hash=content_hash,
                storage_path=storage_path,
                extracted_text=text,
            )
        except UniqueViolationError as exc:
            await self._storage.delete_many([storage_path])
            raise ConflictError("Another version was added at the same time; retry.") from exc
        except Exception:
            await self._storage.delete_many([storage_path])
            raise

        if await self._selected_id(user) is None:
            await self._profiles.set_selected_resume(user.id, resume.id)

        logger.info(
            "resume_uploaded",
            user_id=user.id,
            resume_id=resume.id,
            version=version_number,
            kind=kind,
            chars=len(text),
        )
        return await self.get(user, resume.id)

    async def select(self, user: User, resume_id: str) -> ResumeOut:
        resume = await self._require(user, resume_id)
        await self._profiles.set_selected_resume(user.id, resume.id)
        return resume_out(resume, selected_resume_id=resume.id)

    async def delete(self, user: User, resume_id: str) -> None:
        resume = await self._require(user, resume_id)
        paths = await self._resumes.list_storage_paths(resume.id)
        # Rows first (cascade + SetNull on the selection), files best-effort after.
        await self._resumes.delete(resume.id)
        await self._storage.delete_many(paths)
        logger.info("resume_deleted", user_id=user.id, resume_id=resume.id, files=len(paths))

    async def get_version(self, user: User, version_id: str) -> ResumeVersion:
        version = await self._resumes.get_version_for_user(version_id, user.id)
        if version is None:
            raise NotFoundError("Resume version not found.")
        return version

    async def file_path(self, user: User, version_id: str) -> tuple[Path, ResumeVersion]:
        version = await self.get_version(user, version_id)
        path = self._storage.path_for(version.storagePath)
        if not path.is_file():
            raise NotFoundError("The original file is no longer available.")
        return path, version

    async def selected_version(self, user: User) -> ResumeVersion | None:
        """Latest version of the selected resume, or None when nothing is selected."""
        selected = await self._selected_id(user)
        if selected is None:
            return None
        latest = await self._resumes.latest_version(selected)
        if latest is None:
            return None
        return await self._resumes.get_version_for_user(latest.id, user.id)

    async def _selected_id(self, user: User) -> str | None:
        profile = await self._profiles.get_by_user_id(user.id)
        return getattr(profile, "selectedResumeId", None) if profile else None

    async def _require(self, user: User, resume_id: str) -> Resume:
        resume = await self._resumes.get_for_user(resume_id, user.id)
        if resume is None:
            raise NotFoundError("Resume not found.")
        return resume


def _default_title(filename: str) -> str:
    stem = PurePosixPath(filename or "").stem.replace("_", " ").replace("-", " ").strip()
    return stem[:200] or "Resume"


def _safe_filename(filename: str, kind: str) -> str:
    name = PurePosixPath(filename or "").name.strip() or f"resume.{kind}"
    return name[:255]
