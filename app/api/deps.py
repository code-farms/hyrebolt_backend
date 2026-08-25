from typing import Annotated

import jwt
import redis.asyncio as redis
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.exceptions import RateLimitedError, UnauthorizedError
from app.core.http import get_shared_http_client
from app.core.redis import get_redis_client
from app.core.security import decode_token
from app.db.client import prisma_client
from app.db.generated import Prisma
from app.db.generated.models import User
from app.repositories import (
    CompanyRepository,
    JobRepository,
    JobSourceListingRepository,
    JobSourceRepository,
    ProfileRepository,
    SearchRunRepository,
    SkillRepository,
    UserRepository,
)
from app.services.auth_service import AuthService
from app.services.deduplication_service import DeduplicationService
from app.services.discovery_service import DiscoveryService
from app.services.duplicate_detection_service import DuplicateDetectionService
from app.services.health_service import HealthService
from app.services.normalization_service import NormalizationService
from app.services.profile_service import ProfileService
from app.sources import SourceRegistry

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


def get_profile_repository(prisma: PrismaDep) -> ProfileRepository:
    return ProfileRepository(prisma)


ProfileRepositoryDep = Annotated[ProfileRepository, Depends(get_profile_repository)]


def get_auth_service(
    users: UserRepositoryDep,
    profiles: ProfileRepositoryDep,
    redis_client: RedisDep,
    settings: SettingsDep,
) -> AuthService:
    return AuthService(users=users, profiles=profiles, redis_client=redis_client, settings=settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_profile_service(
    profiles: ProfileRepositoryDep, skills: SkillRepositoryDep
) -> ProfileService:
    return ProfileService(profiles=profiles, skills=skills)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]

_source_registry: SourceRegistry | None = None


def get_source_registry() -> SourceRegistry:
    """Lazy singleton over the shared httpx client. Nothing here touches the
    network — connectors only do when their methods are invoked (Phase 5)."""
    global _source_registry
    if _source_registry is None:
        _source_registry = SourceRegistry(get_shared_http_client())
    return _source_registry


SourceRegistryDep = Annotated[SourceRegistry, Depends(get_source_registry)]


def get_search_run_repository(prisma: PrismaDep) -> SearchRunRepository:
    return SearchRunRepository(prisma)


SearchRunRepositoryDep = Annotated[SearchRunRepository, Depends(get_search_run_repository)]


def get_discovery_service(
    registry: SourceRegistryDep,
    prisma: PrismaDep,
    search_runs: SearchRunRepositoryDep,
    redis_client: RedisDep,
    settings: SettingsDep,
) -> DiscoveryService:
    return DiscoveryService(
        registry=registry,
        job_sources=JobSourceRepository(prisma),
        search_runs=search_runs,
        normalizer=NormalizationService(),
        deduper=DeduplicationService(
            jobs=JobRepository(prisma),
            listings=JobSourceListingRepository(prisma),
            companies=CompanyRepository(prisma),
            sources=JobSourceRepository(prisma),
            detector=DuplicateDetectionService(settings),
            settings=settings,
        ),
        redis_client=redis_client,
        settings=settings,
    )


DiscoveryServiceDep = Annotated[DiscoveryService, Depends(get_discovery_service)]

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    users: UserRepositoryDep,
    settings: SettingsDep,
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required.", "invalid_token")
    try:
        payload = decode_token(settings, credentials.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired.", "token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid access token.", "invalid_token") from exc
    user = await users.get_by_id(str(payload.get("sub", "")))
    if user is None or not user.isActive or user.deletedAt is not None:
        raise UnauthorizedError("Invalid access token.", "invalid_token")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def rate_limit(scope: str, limit_attr: str = "auth_rate_limit_per_minute"):  # type: ignore[no-untyped-def]  # returns a FastAPI Depends marker
    """Fixed-window per-IP rate limiter backed by Redis (INCR + EXPIRE)."""

    async def dependency(request: Request, redis_client: RedisDep, settings: SettingsDep) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{scope}:{client_ip}"
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 60)
        if count > getattr(settings, limit_attr):
            raise RateLimitedError("Too many attempts. Try again in a minute.")

    return Depends(dependency)
