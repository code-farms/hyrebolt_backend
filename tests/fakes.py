"""In-memory stand-ins for the repositories and Redis, so API tests run
hermetically (no Postgres/Redis) via FastAPI dependency_overrides."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.db.generated.enums import RemotePreference


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def incr(self, key: str) -> int:
        value = int(self.store.get(key, "0")) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def ping(self) -> bool:
        return True


@dataclass
class FakeUser:
    id: str
    email: str
    passwordHash: str
    name: str | None = None
    isActive: bool = True
    deletedAt: datetime | None = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeProfile:
    id: str
    userId: str
    phone: str | None = None
    currentRole: str | None = None
    yearsOfExperience: float | None = None
    targetRoles: list[str] = field(default_factory=list)
    preferredLocations: list[str] = field(default_factory=list)
    remotePreference: RemotePreference = RemotePreference.ANY
    minimumSalary: int | None = None
    preferredSalary: int | None = None
    salaryCurrency: str = "INR"
    noticePeriodDays: int | None = None
    education: Any | None = None
    industries: list[str] = field(default_factory=list)
    preferredCompanies: list[str] = field(default_factory=list)
    excludedCompanies: list[str] = field(default_factory=list)
    # Notification preferences (Phase 10), schema defaults mirrored.
    emailEnabled: bool = True
    telegramEnabled: bool = False
    telegramChatId: str | None = None
    dailyDigestEnabled: bool = True
    digestMinScore: int = 70
    digestMaxJobs: int = 10
    digestTime: str | None = None
    skills: list[SimpleNamespace] = field(default_factory=list)


class FakeDB:
    """Shared state for the fake repositories."""

    def __init__(self) -> None:
        self.users: dict[str, FakeUser] = {}  # by id
        self.profiles: dict[str, FakeProfile] = {}  # by userId
        self.skills: dict[str, SimpleNamespace] = {}  # by normalizedName


class FakeUserRepository:
    def __init__(self, db: FakeDB) -> None:
        self._db = db

    async def get_by_email(self, email: str) -> FakeUser | None:
        return next((u for u in self._db.users.values() if u.email == email), None)

    async def get_by_id(self, user_id: str) -> FakeUser | None:
        return self._db.users.get(user_id)

    async def create(self, *, email: str, password_hash: str, name: str | None = None) -> FakeUser:
        user = FakeUser(id=uuid.uuid4().hex, email=email, passwordHash=password_hash, name=name)
        self._db.users[user.id] = user
        return user


class FakeProfileRepository:
    def __init__(self, db: FakeDB) -> None:
        self._db = db

    async def get_by_user_id(self, user_id: str) -> FakeProfile | None:
        return self._db.profiles.get(user_id)

    async def upsert_for_user(self, user_id: str, data: dict[str, Any]) -> FakeProfile:
        profile = self._db.profiles.get(user_id)
        if profile is None:
            profile = FakeProfile(id=uuid.uuid4().hex, userId=user_id)
            self._db.profiles[user_id] = profile
        for key, value in data.items():
            setattr(profile, key, value)
        return profile

    async def replace_skills(
        self, profile_id: str, items: list[tuple[str, str, float | None]]
    ) -> None:
        profile = next(p for p in self._db.profiles.values() if p.id == profile_id)
        by_id = {s.id: s for s in self._db.skills.values()}
        profile.skills = [
            SimpleNamespace(
                skill=by_id[skill_id],
                proficiency=proficiency,
                yearsOfExperience=years,
            )
            for skill_id, proficiency, years in items
        ]


class FakeSkillRepository:
    def __init__(self, db: FakeDB) -> None:
        self._db = db

    @staticmethod
    def normalize(name: str) -> str:
        return name.strip().lower()

    async def upsert_by_name(
        self, name: str, *, category: str | None = None
    ) -> SimpleNamespace:
        normalized = self.normalize(name)
        skill = self._db.skills.get(normalized)
        if skill is None:
            skill = SimpleNamespace(
                id=uuid.uuid4().hex, name=name, normalizedName=normalized, category=category
            )
            self._db.skills[normalized] = skill
        return skill
