from typing import Any

from app.db.generated.models import UserProfile
from app.repositories.base import BaseRepository


class ProfileRepository(BaseRepository):
    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        return await self._prisma.userprofile.find_unique(
            where={"userId": user_id},
            include={"skills": {"include": {"skill": True}}},
        )

    async def upsert_for_user(self, user_id: str, data: dict[str, Any]) -> UserProfile:
        return await self._prisma.userprofile.upsert(
            where={"userId": user_id},
            data={"create": {"userId": user_id, **data}, "update": data},
        )

    async def set_selected_resume(self, user_id: str, resume_id: str | None) -> UserProfile:
        """Phase 14: one write; the column is unique so two resumes can never
        both be selected, and deleting the resume nulls it (SetNull)."""
        return await self.upsert_for_user(user_id, {"selectedResumeId": resume_id})

    async def replace_skills(
        self, profile_id: str, items: list[tuple[str, str, float | None]]
    ) -> None:
        """items: (skillId, proficiency, yearsOfExperience). Full replace."""
        async with self._prisma.tx() as tx:
            await tx.userskill.delete_many(where={"profileId": profile_id})
            for skill_id, proficiency, years in items:
                await tx.userskill.create(
                    data={
                        "profileId": profile_id,
                        "skillId": skill_id,
                        "proficiency": proficiency,  # type: ignore[typeddict-item]
                        "yearsOfExperience": years,
                    }
                )
