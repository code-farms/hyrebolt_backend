"""Database access layer: all Prisma queries live in repositories so services
stay persistence-agnostic. Inject via the factories in ``app.api.deps``."""

from app.repositories.base import BaseRepository
from app.repositories.job_repository import JobRepository
from app.repositories.job_source_repository import JobSourceRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "JobRepository",
    "JobSourceRepository",
    "ProfileRepository",
    "SkillRepository",
    "UserRepository",
]
