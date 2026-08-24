from app.db.generated.models import Skill
from app.repositories.base import BaseRepository


class SkillRepository(BaseRepository):
    @staticmethod
    def normalize(name: str) -> str:
        return name.strip().lower()

    async def upsert_by_name(self, name: str, *, category: str | None = None) -> Skill:
        normalized = self.normalize(name)
        return await self._prisma.skill.upsert(
            where={"normalizedName": normalized},
            data={
                "create": {"name": name, "normalizedName": normalized, "category": category},
                "update": {"category": category},
            },
        )
