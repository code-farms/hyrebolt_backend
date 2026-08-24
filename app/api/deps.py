from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.redis import get_redis_client
from app.db.client import prisma_client
from app.db.generated import Prisma
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
