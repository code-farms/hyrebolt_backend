from app.db.generated.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_email(self, email: str) -> User | None:
        return await self._prisma.user.find_unique(where={"email": email})

    async def upsert_by_email(
        self, email: str, *, password_hash: str, name: str | None = None
    ) -> User:
        return await self._prisma.user.upsert(
            where={"email": email},
            data={
                "create": {"email": email, "passwordHash": password_hash, "name": name},
                "update": {"name": name},
            },
        )
