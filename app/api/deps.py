from pathlib import Path
from typing import Annotated

import jwt
import redis.asyncio as redis
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError

from app.ai import ChatCompletionsProvider, LLMProvider, MockLLMProvider
from app.core.config import Settings, get_settings
from app.core.exceptions import DependencyUnavailableError, RateLimitedError, UnauthorizedError
from app.core.http import get_shared_http_client
from app.core.redis import get_redis_client
from app.core.security import decode_token
from app.db.client import prisma_client
from app.db.generated import Prisma
from app.db.generated.models import User
from app.notifications import build_providers
from app.repositories import (
    AnalyticsRepository,
    ApplicationDraftRepository,
    ApplicationRepository,
    CompanyRepository,
    CompanyWatchlistRepository,
    JobAnalysisRepository,
    JobMatchRepository,
    JobRepository,
    JobSourceListingRepository,
    JobSourceRepository,
    NotificationRepository,
    PreferenceSignalRepository,
    ProfileRepository,
    ResumeAnalysisRepository,
    ResumeGapRepository,
    ResumeRepository,
    SavedJobRepository,
    SearchRunRepository,
    SkillRepository,
    UserRepository,
)
from app.services.agent_status_service import AgentStatusService
from app.services.ai_matcher import AIMatcher
from app.services.analytics_service import AnalyticsService
from app.services.application_assistant_service import ApplicationAssistantService
from app.services.application_service import ApplicationService
from app.services.auth_service import AuthService
from app.services.candidate_matching_service import CandidateMatchingService
from app.services.company_service import CompanyService
from app.services.daily_digest_service import DailyDigestService
from app.services.deduplication_service import DeduplicationService
from app.services.discovery_service import DiscoveryService
from app.services.duplicate_detection_service import DuplicateDetectionService
from app.services.health_service import HealthService
from app.services.job_analysis_service import JobAnalysisService
from app.services.normalization_service import NormalizationService
from app.services.preference_signal_service import PreferenceSignalService
from app.services.profile_service import ProfileService
from app.services.ranking_service import RankingService, RankingWeights
from app.services.resume_analysis_service import ResumeAnalysisService
from app.services.resume_gap_service import ResumeGapService
from app.services.resume_service import ResumeService
from app.services.resume_storage import ResumeStorage
from app.services.rule_based_matcher import RuleBasedMatcher
from app.services.watchlist_boards import WatchlistBoardsProvider
from app.sources import SourceRegistry

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_prisma() -> Prisma:
    return prisma_client


PrismaDep = Annotated[Prisma, Depends(get_prisma)]


def get_redis(settings: SettingsDep) -> redis.Redis:
    return get_redis_client(settings)


RedisDep = Annotated[redis.Redis, Depends(get_redis)]


def get_health_service(
    prisma: PrismaDep, redis_client: RedisDep, settings: SettingsDep
) -> HealthService:
    return HealthService(
        prisma=prisma, redis_client=redis_client, expose_details=not settings.is_production
    )


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
        board_provider=WatchlistBoardsProvider(CompanyRepository(prisma)),
    )


DiscoveryServiceDep = Annotated[DiscoveryService, Depends(get_discovery_service)]


def get_llm_provider(settings: SettingsDep) -> LLMProvider:
    if settings.llm_provider == "api" and settings.llm_api_key:
        return ChatCompletionsProvider(
            get_shared_http_client(),
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return MockLLMProvider()


LLMProviderDep = Annotated[LLMProvider, Depends(get_llm_provider)]


def get_job_analysis_service(
    provider: LLMProviderDep, prisma: PrismaDep, settings: SettingsDep
) -> JobAnalysisService:
    return JobAnalysisService(
        provider=provider,
        analyses=JobAnalysisRepository(prisma),
        jobs=JobRepository(prisma),
        settings=settings,
    )


JobAnalysisServiceDep = Annotated[JobAnalysisService, Depends(get_job_analysis_service)]


def get_job_match_repository(prisma: PrismaDep) -> JobMatchRepository:
    return JobMatchRepository(prisma)


JobMatchRepositoryDep = Annotated[JobMatchRepository, Depends(get_job_match_repository)]


def get_matching_service(
    provider: LLMProviderDep,
    prisma: PrismaDep,
    matches: JobMatchRepositoryDep,
    settings: SettingsDep,
) -> CandidateMatchingService:
    return CandidateMatchingService(
        matcher=RuleBasedMatcher(settings),
        ai_matcher=AIMatcher(provider),
        matches=matches,
        profiles=ProfileRepository(prisma),
        analyses=JobAnalysisRepository(prisma),
        jobs=JobRepository(prisma),
        watchlists=CompanyWatchlistRepository(prisma),
    )


CandidateMatchingServiceDep = Annotated[
    CandidateMatchingService, Depends(get_matching_service)
]


def get_company_repository(prisma: PrismaDep) -> CompanyRepository:
    return CompanyRepository(prisma)


CompanyRepositoryDep = Annotated[CompanyRepository, Depends(get_company_repository)]


def get_company_watchlist_repository(prisma: PrismaDep) -> CompanyWatchlistRepository:
    return CompanyWatchlistRepository(prisma)


CompanyWatchlistRepositoryDep = Annotated[
    CompanyWatchlistRepository, Depends(get_company_watchlist_repository)
]


def get_company_service(
    companies: CompanyRepositoryDep,
    watchlists: CompanyWatchlistRepositoryDep,
    jobs: JobRepositoryDep,
    matches: JobMatchRepositoryDep,
    matching: CandidateMatchingServiceDep,
    settings: SettingsDep,
) -> CompanyService:
    return CompanyService(
        companies=companies,
        watchlists=watchlists,
        jobs=jobs,
        matches=matches,
        matching=matching,
        settings=settings,
    )


CompanyServiceDep = Annotated[CompanyService, Depends(get_company_service)]

_resume_storage: ResumeStorage | None = None


def get_resume_storage(settings: SettingsDep) -> ResumeStorage:
    global _resume_storage
    if _resume_storage is None:
        _resume_storage = ResumeStorage(Path(settings.resume_storage_dir))
    return _resume_storage


ResumeStorageDep = Annotated[ResumeStorage, Depends(get_resume_storage)]


def get_resume_repository(prisma: PrismaDep) -> ResumeRepository:
    return ResumeRepository(prisma)


ResumeRepositoryDep = Annotated[ResumeRepository, Depends(get_resume_repository)]


def get_resume_service(
    resumes: ResumeRepositoryDep,
    profiles: ProfileRepositoryDep,
    storage: ResumeStorageDep,
    settings: SettingsDep,
) -> ResumeService:
    return ResumeService(resumes=resumes, profiles=profiles, storage=storage, settings=settings)


ResumeServiceDep = Annotated[ResumeService, Depends(get_resume_service)]


def get_resume_analysis_service(
    provider: LLMProviderDep, prisma: PrismaDep, skills: SkillRepositoryDep, settings: SettingsDep
) -> ResumeAnalysisService:
    return ResumeAnalysisService(
        provider=provider,
        analyses=ResumeAnalysisRepository(prisma),
        skills=skills,
        settings=settings,
    )


ResumeAnalysisServiceDep = Annotated[ResumeAnalysisService, Depends(get_resume_analysis_service)]


def get_resume_gap_service(
    provider: LLMProviderDep,
    prisma: PrismaDep,
    job_analysis: JobAnalysisServiceDep,
    profiles: ProfileRepositoryDep,
    skills: SkillRepositoryDep,
    settings: SettingsDep,
) -> ResumeGapService:
    return ResumeGapService(
        provider=provider,
        gaps=ResumeGapRepository(prisma),
        job_analysis=job_analysis,
        profiles=profiles,
        skills=skills,
        settings=settings,
    )


ResumeGapServiceDep = Annotated[ResumeGapService, Depends(get_resume_gap_service)]


def get_application_draft_repository(prisma: PrismaDep) -> ApplicationDraftRepository:
    return ApplicationDraftRepository(prisma)


ApplicationDraftRepositoryDep = Annotated[
    ApplicationDraftRepository, Depends(get_application_draft_repository)
]


def get_application_assistant_service(
    provider: LLMProviderDep,
    drafts: ApplicationDraftRepositoryDep,
    profiles: ProfileRepositoryDep,
    companies: CompanyRepositoryDep,
    resumes: ResumeServiceDep,
    skills: SkillRepositoryDep,
    settings: SettingsDep,
) -> ApplicationAssistantService:
    return ApplicationAssistantService(
        provider=provider,
        drafts=drafts,
        profiles=profiles,
        companies=companies,
        resumes=resumes,
        skills=skills,
        settings=settings,
    )


ApplicationAssistantServiceDep = Annotated[
    ApplicationAssistantService, Depends(get_application_assistant_service)
]


def get_preference_signal_repository(prisma: PrismaDep) -> PreferenceSignalRepository:
    return PreferenceSignalRepository(prisma)


PreferenceSignalRepositoryDep = Annotated[
    PreferenceSignalRepository, Depends(get_preference_signal_repository)
]


def get_preference_signal_service(
    signals: PreferenceSignalRepositoryDep, prisma: PrismaDep
) -> PreferenceSignalService:
    return PreferenceSignalService(signals, JobAnalysisRepository(prisma))


PreferenceSignalServiceDep = Annotated[
    PreferenceSignalService, Depends(get_preference_signal_service)
]


def _build_ranking_service(prisma: Prisma, matches: JobMatchRepository, settings: Settings) -> RankingService:
    return RankingService(
        matches,
        jobs=JobRepository(prisma),
        signals=PreferenceSignalService(
            PreferenceSignalRepository(prisma), JobAnalysisRepository(prisma)
        ),
        weights=RankingWeights.from_settings(settings),
    )


def get_ranking_service(
    matches: JobMatchRepositoryDep,
    jobs: JobRepositoryDep,
    signals: PreferenceSignalServiceDep,
    settings: SettingsDep,
) -> RankingService:
    return RankingService(
        matches, jobs=jobs, signals=signals, weights=RankingWeights.from_settings(settings)
    )


RankingServiceDep = Annotated[RankingService, Depends(get_ranking_service)]


def get_agent_status_service(
    prisma: PrismaDep,
    matches: JobMatchRepositoryDep,
    search_runs: SearchRunRepositoryDep,
    redis_client: RedisDep,
    settings: SettingsDep,
) -> AgentStatusService:
    return AgentStatusService(
        search_runs=search_runs,
        matches=matches,
        notifications=NotificationRepository(prisma),
        redis_client=redis_client,
        settings=settings,
    )


AgentStatusServiceDep = Annotated[AgentStatusService, Depends(get_agent_status_service)]


def get_analytics_repository(prisma: PrismaDep) -> AnalyticsRepository:
    return AnalyticsRepository(prisma)


AnalyticsRepositoryDep = Annotated[AnalyticsRepository, Depends(get_analytics_repository)]


def get_analytics_service(
    analytics: AnalyticsRepositoryDep, settings: SettingsDep
) -> AnalyticsService:
    return AnalyticsService(analytics, settings=settings)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


def get_saved_job_repository(prisma: PrismaDep) -> SavedJobRepository:
    return SavedJobRepository(prisma)


SavedJobRepositoryDep = Annotated[SavedJobRepository, Depends(get_saved_job_repository)]


def get_application_repository(prisma: PrismaDep) -> ApplicationRepository:
    return ApplicationRepository(prisma)


ApplicationRepositoryDep = Annotated[
    ApplicationRepository, Depends(get_application_repository)
]


def get_application_service(
    applications: ApplicationRepositoryDep, signals: PreferenceSignalServiceDep
) -> ApplicationService:
    return ApplicationService(applications, signals=signals)


ApplicationServiceDep = Annotated[ApplicationService, Depends(get_application_service)]


def get_notification_repository(prisma: PrismaDep) -> NotificationRepository:
    return NotificationRepository(prisma)


NotificationRepositoryDep = Annotated[
    NotificationRepository, Depends(get_notification_repository)
]


def get_daily_digest_service(
    prisma: PrismaDep,
    matches: JobMatchRepositoryDep,
    notifications: NotificationRepositoryDep,
    settings: SettingsDep,
) -> DailyDigestService:
    return DailyDigestService(
        ranking=_build_ranking_service(prisma, matches, settings),
        profiles=ProfileRepository(prisma),
        notifications=notifications,
        providers=build_providers(settings, get_shared_http_client()),
    )


DailyDigestServiceDep = Annotated[DailyDigestService, Depends(get_daily_digest_service)]

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
        try:
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, 60)
        except RedisError as exc:
            # Fail closed with an honest status: the limiter's backing store is
            # down, which is a 503, not an internal error.
            raise DependencyUnavailableError("Rate limiter unavailable. Try again shortly.") from exc
        if count > getattr(settings, limit_attr):
            raise RateLimitedError("Too many attempts. Try again in a minute.")

    return Depends(dependency)
