from app.db.generated.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_email(self, email: str) -> User | None:
        return await self._prisma.user.find_unique(where={"email": email})

    async def get_by_id(self, user_id: str) -> User | None:
        return await self._prisma.user.find_unique(where={"id": user_id})

    async def list_active(self) -> list[User]:
        return await self._prisma.user.find_many(
            where={"isActive": True, "deletedAt": None}
        )

    async def create(self, *, email: str, password_hash: str, name: str | None = None) -> User:
        return await self._prisma.user.create(
            data={"email": email, "passwordHash": password_hash, "name": name}
        )

    async def upsert_by_email(
        self, email: str, *, password_hash: str, name: str | None = None
    ) -> User:
        return await self._prisma.user.upsert(
            where={"email": email},
            data={
                "create": {"email": email, "passwordHash": password_hash, "name": name},
                "update": {"name": name, "passwordHash": password_hash},
            },
        )
