"""Builds the agent's service graph for the worker process — the same wiring
app/api/deps.py does per-request, but over the module singletons and built
once at worker startup."""

from app.ai import ChatCompletionsProvider, LLMProvider, MockLLMProvider
from app.core.config import Settings
from app.core.http import get_shared_http_client
from app.core.redis import get_redis_client
from app.db.client import prisma_client
from app.notifications import build_providers
from app.repositories import (
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
    SearchRunRepository,
    UserRepository,
)
from app.services.ai_matcher import AIMatcher
from app.services.candidate_matching_service import CandidateMatchingService
from app.services.daily_digest_service import DailyDigestService
from app.services.deduplication_service import DeduplicationService
from app.services.discovery_service import DiscoveryService
from app.services.duplicate_detection_service import DuplicateDetectionService
from app.services.job_analysis_service import JobAnalysisService
from app.services.normalization_service import NormalizationService
from app.services.preference_signal_service import PreferenceSignalService
from app.services.ranking_service import RankingService, RankingWeights
from app.services.rule_based_matcher import RuleBasedMatcher
from app.services.watchlist_boards import WatchlistBoardsProvider
from app.sources import SourceRegistry
from app.worker.tasks import AgentTasks


def _build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "api" and settings.llm_api_key:
        return ChatCompletionsProvider(
            get_shared_http_client(),
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return MockLLMProvider()


def build_agent_tasks(settings: Settings) -> AgentTasks:
    prisma = prisma_client
    redis_client = get_redis_client(settings)
    provider = _build_llm_provider(settings)
    matches = JobMatchRepository(prisma)
    watchlists = CompanyWatchlistRepository(prisma)

    discovery = DiscoveryService(
        registry=SourceRegistry(get_shared_http_client()),
        job_sources=JobSourceRepository(prisma),
        search_runs=SearchRunRepository(prisma),
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
    analysis = JobAnalysisService(
        provider=provider,
        analyses=JobAnalysisRepository(prisma),
        jobs=JobRepository(prisma),
        settings=settings,
    )
    matching = CandidateMatchingService(
        matcher=RuleBasedMatcher(settings),
        ai_matcher=AIMatcher(provider),
        matches=matches,
        profiles=ProfileRepository(prisma),
        analyses=JobAnalysisRepository(prisma),
        jobs=JobRepository(prisma),
        watchlists=watchlists,
    )
    digest = DailyDigestService(
        ranking=RankingService(
            matches,
            jobs=JobRepository(prisma),
            signals=PreferenceSignalService(
                PreferenceSignalRepository(prisma), JobAnalysisRepository(prisma)
            ),
            weights=RankingWeights.from_settings(settings),
        ),
        profiles=ProfileRepository(prisma),
        notifications=NotificationRepository(prisma),
        providers=build_providers(settings, get_shared_http_client()),
    )
    return AgentTasks(
        discovery=discovery,
        analysis=analysis,
        matching=matching,
        digest=digest,
        users=UserRepository(prisma),
        profiles=ProfileRepository(prisma),
        redis_client=redis_client,
        settings=settings,
        watchlists=watchlists,
    )
