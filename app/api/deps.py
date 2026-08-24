from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.redis import get_redis_client
from app.db.client import prisma_client
from app.db.generated import Prisma
from app.repositories import (
    JobRepository,
    JobSourceRepository,
    SkillRepository,
    UserRepository,
)
from app.services.health_service import HealthService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_prisma() -> Prisma:
    return prisma_client


PrismaDep = Annotated[Prisma, Depends(get_prisma)]


def get_redis(settings: SettingsDep) -> redis.Redis:
    return get_redis_client(settings)


RedisDep = Annotated[redis.Redis, Depends(get_redis)]


def get_health_service(prisma: PrismaDep, redis_client: RedisDep) -> HealthService:
    return HealthService(prisma=prisma, redis_client=redis_client)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


def get_user_repository(prisma: PrismaDep) -> UserRepository:
    return UserRepository(prisma)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_job_repository(prisma: PrismaDep) -> JobRepository:
    return JobRepository(prisma)


JobRepositoryDep = Annotated[JobRepository, Depends(get_job_repository)]


def get_job_source_repository(prisma: PrismaDep) -> JobSourceRepository:
    return JobSourceRepository(prisma)


JobSourceRepositoryDep = Annotated[JobSourceRepository, Depends(get_job_source_repository)]


def get_skill_repository(prisma: PrismaDep) -> SkillRepository:
    return SkillRepository(prisma)


SkillRepositoryDep = Annotated[SkillRepository, Depends(get_skill_repository)]
