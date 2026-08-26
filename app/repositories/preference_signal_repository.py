from collections.abc import Iterable
from typing import Any

from app.db.generated.models import UserPreferenceSignal
from app.models import PreferenceSignalKind
from app.repositories.base import BaseRepository


class PreferenceSignalRepository(BaseRepository):
    async def list_for_user(self, user_id: str) -> list[UserPreferenceSignal]:
        return await self._prisma.userpreferencesignal.find_many(
            where={"userId": user_id}, order={"createdAt": "asc"}
        )

    async def upsert(
        self, user_id: str, job_id: str, kind: PreferenceSignalKind, data: dict[str, Any]
    ) -> UserPreferenceSignal:
        """One row per (user, job, kind); repeating an action refreshes the
        snapshot and the timestamp instead of duplicating."""
        return await self._prisma.userpreferencesignal.upsert(
            where={"userId_jobId_kind": {"userId": user_id, "jobId": job_id, "kind": kind}},  # type: ignore[typeddict-item]
            data={
                "create": {"userId": user_id, "jobId": job_id, "kind": kind, **data},
                "update": {**data, "createdAt": data.get("createdAt")}
                if "createdAt" in data
                else data,
            },  # type: ignore[typeddict-item]
        )

    async def delete_kinds(
        self, user_id: str, job_id: str, kinds: Iterable[PreferenceSignalKind]
    ) -> int:
        return await self._prisma.userpreferencesignal.delete_many(
            where={"userId": user_id, "jobId": job_id, "kind": {"in": list(kinds)}}  # type: ignore[typeddict-item]
        )

    async def delete_by_id(self, user_id: str, signal_id: str) -> int:
        # Ownership is part of the predicate: another user's id deletes nothing.
        return await self._prisma.userpreferencesignal.delete_many(
            where={"id": signal_id, "userId": user_id}
        )

    async def delete_all(self, user_id: str) -> int:
        return await self._prisma.userpreferencesignal.delete_many(where={"userId": user_id})
