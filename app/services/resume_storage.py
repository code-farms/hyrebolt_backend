"""Local-disk storage for uploaded resume originals (Phase 14).

The extracted text lives in the database, so this store is only read for
downloads; a lost file degrades the feature rather than breaking analysis.
Paths are relative to the configured root: {userId}/{versionId}.{ext}."""

import asyncio
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)


class ResumeStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, storage_path: str) -> Path:
        candidate = (self._root / storage_path).resolve()
        if self._root.resolve() not in candidate.parents:
            raise ValueError("storage path escapes the resume root")
        return candidate

    async def save(self, user_id: str, version_id: str, ext: str, data: bytes) -> str:
        relative = f"{user_id}/{version_id}.{ext}"
        target = self.path_for(relative)

        def _write() -> None:
            # Resumes are personal documents: owner-only on disk, so a shared
            # volume or host account never exposes them.
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(data)
            target.chmod(0o600)

        await asyncio.to_thread(_write)
        return relative

    async def delete_many(self, storage_paths: list[str]) -> None:
        """Best effort: the DB rows are already gone, so a missing or locked
        file is logged, never raised."""

        def _unlink(path: Path) -> None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("resume_file_delete_failed", path=str(path), error=str(exc))

        for storage_path in storage_paths:
            try:
                target = self.path_for(storage_path)
            except ValueError:
                logger.warning("resume_file_path_invalid", path=storage_path)
                continue
            await asyncio.to_thread(_unlink, target)
