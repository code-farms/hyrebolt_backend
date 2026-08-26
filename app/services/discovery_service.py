import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
import structlog

from app.core.config import Settings
from app.core.exceptions import InvalidInputError
from app.core.logging import get_logger
from app.db.generated.models import SearchRun
from app.models import SearchRunStatus, SearchTrigger
from app.repositories import JobSourceRepository, SearchRunRepository
from app.schemas.search import SearchQuery
from app.services.deduplication_service import DeduplicationService
from app.services.normalization_service import NormalizationService
from app.sources import (
    JobSourceConfig,
    NormalizedJob,
    SourceError,
    SourceRateLimitedError,
    SourceRegistry,
    SourceSearchParams,
    merge_config,
)
from app.sources.boards import merge_boards
from app.sources.throttle import make_source_throttle

logger = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]
BoardProvider = Callable[[], Awaitable[list[dict[str, str]]]]

CAREERS_SOURCE = "company_careers"


@dataclass
class SourceFetchResult:
    source_name: str
    jobs: list[NormalizedJob] = field(default_factory=list)
    error: str | None = None


def to_source_params(
    query: SearchQuery, *, max_per_source: int, now: datetime
) -> SourceSearchParams:
    return SourceSearchParams(
        # targetRoles merge into keywords: connectors have one free-text channel.
        keywords=tuple(dict.fromkeys([*query.keywords, *query.targetRoles])),
        locations=tuple(query.locations),
        remote=query.remote,
        companies=tuple(query.companies),
        postedSince=(
            now - timedelta(days=query.datePosted) if query.datePosted is not None else None
        ),
        limit=min(query.limitPerSource or max_per_source, max_per_source),
    )


async def retry_source_call[T](
    call: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float,
    max_delay: float,
    jitter: float,
    sleep: Sleep,
    source_name: str,
) -> T:
    """Retries only errors flagged retryable, with exponential backoff.
    SourceRateLimitedError.retry_after acts as a delay floor."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return await call()
        except SourceError as exc:
            if not exc.retryable or attempt >= attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if jitter > 0:
                delay += random.uniform(0, jitter)
            if isinstance(exc, SourceRateLimitedError) and exc.retry_after is not None:
                delay = max(delay, exc.retry_after)
            logger.warning(
                "source_search_retry",
                source=source_name,
                attempt=attempt,
                delay_seconds=round(delay, 2),
                error=exc.message,
            )
            await sleep(delay)


class DiscoveryService:
    def __init__(
        self,
        registry: SourceRegistry,
        job_sources: JobSourceRepository,
        search_runs: SearchRunRepository,
        normalizer: NormalizationService,
        deduper: DeduplicationService,
        redis_client: redis.Redis,
        settings: Settings,
        sleep: Sleep = asyncio.sleep,
        board_provider: BoardProvider | None = None,
    ) -> None:
        self._registry = registry
        self._job_sources = job_sources
        self._search_runs = search_runs
        self._normalizer = normalizer
        self._deduper = deduper
        self._redis = redis_client
        self._settings = settings
        self._sleep = sleep
        self._board_provider = board_provider

    async def run_search(
        self,
        *,
        user_id: str | None,
        query: SearchQuery,
        trigger: SearchTrigger = SearchTrigger.MANUAL,
    ) -> SearchRun:
        runnable, rejected = await self._select_sources(query.sources)
        attempted = [*runnable, *rejected]

        run = await self._search_runs.create(
            user_id=user_id,
            trigger=trigger,
            query=query.model_dump(mode="json"),
            sources_attempted=attempted,
        )
        structlog.contextvars.bind_contextvars(run_id=run.id)
        logger.info(
            "search_run_started", trigger=trigger, user_id=user_id, sources=attempted
        )
        try:
            return await self._execute(run, query, runnable, rejected)
        except Exception as exc:
            await self._search_runs.finish(
                run.id,
                status=SearchRunStatus.FAILED,
                sources_succeeded=[],
                sources_failed=attempted,
                jobs_found=0,
                jobs_new=0,
                jobs_duplicate=0,
                error_summary=f"internal error: {exc}",
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("run_id")

    async def _execute(
        self,
        run: SearchRun,
        query: SearchQuery,
        runnable: dict[str, JobSourceConfig],
        rejected: dict[str, str],
    ) -> SearchRun:
        params = to_source_params(
            query,
            max_per_source=self._settings.discovery_max_jobs_per_source,
            now=datetime.now(UTC),
        )

        # Fetch + normalize concurrently; one source's failure never cancels
        # the others (which is why this is gather, not TaskGroup).
        fetches = await asyncio.gather(
            *(
                self._fetch_source(name, config, params, query)
                for name, config in runnable.items()
            ),
            return_exceptions=True,
        )

        results: list[SourceFetchResult] = []
        for name, outcome in zip(runnable, fetches, strict=True):
            if isinstance(outcome, BaseException):
                logger.error("source_search_crashed", source=name, error=str(outcome))
                results.append(SourceFetchResult(name, error=f"internal error: {outcome}"))
            else:
                results.append(outcome)

        # Persist sequentially so in-batch cross-source duplicates hit the
        # earlier occurrence's committed rows.
        all_jobs = [job for result in results if result.error is None for job in result.jobs]
        persisted = await self._deduper.persist_batch(all_jobs)

        succeeded = [r.source_name for r in results if r.error is None]
        failed = {r.source_name: r.error for r in results if r.error is not None}
        failed.update(rejected)

        if not runnable and not rejected:
            status = SearchRunStatus.COMPLETED  # a no-op run is not a failure
            logger.info("search_run_empty")
        elif not failed:
            status = SearchRunStatus.COMPLETED
        elif succeeded:
            status = SearchRunStatus.PARTIAL
        else:
            status = SearchRunStatus.FAILED

        finished = await self._search_runs.finish(
            run.id,
            status=status,
            sources_succeeded=succeeded,
            sources_failed=sorted(failed),
            jobs_found=persisted.found,
            jobs_new=persisted.new,
            jobs_duplicate=persisted.duplicate,
            error_summary=(
                "; ".join(f"{name}: {message}" for name, message in sorted(failed.items()))
                or None
            ),
        )
        logger.info(
            "search_run_completed",
            status=status,
            jobs_found=persisted.found,
            jobs_new=persisted.new,
            jobs_duplicate=persisted.duplicate,
            sources_failed=sorted(failed),
        )
        return finished

    async def _select_sources(
        self, requested: list[str] | None
    ) -> tuple[dict[str, JobSourceConfig], dict[str, str]]:
        """Returns (runnable {name: merged config}, rejected {name: reason}).
        Unknown names fail fast (422) before a run row exists; requested but
        disabled sources are recorded as failures so the user can see why."""
        known = set(self._registry.list_names())
        if requested is not None:
            unknown = sorted(set(requested) - known)
            if unknown:
                raise InvalidInputError(f"Unknown sources: {', '.join(unknown)}")

        rows = {row.name: row for row in await self._job_sources.list_all()}
        names = list(dict.fromkeys(requested)) if requested is not None else sorted(known)

        runnable: dict[str, JobSourceConfig] = {}
        rejected: dict[str, str] = {}
        for name in names:
            merged = merge_config(self._registry.get_config(name), rows.get(name))
            if merged.enabled:
                runnable[name] = merged
            elif requested is not None:
                rejected[name] = "disabled"
            # not requested + disabled -> simply not attempted
        if CAREERS_SOURCE in runnable and self._board_provider is not None:
            runnable[CAREERS_SOURCE] = await self._with_watchlist_boards(runnable[CAREERS_SOURCE])
        return runnable, rejected

    async def _with_watchlist_boards(self, config: JobSourceConfig) -> JobSourceConfig:
        """Phase 13: boards derived from watchlisted companies' careers URLs
        join the operator-configured ones. A failing lookup is logged, never
        fatal — the watchlist must not be able to sink a search run."""
        assert self._board_provider is not None
        try:
            extra = await self._board_provider()
        except Exception as exc:  # noqa: BLE001 - discovery must survive a watchlist lookup failure
            logger.warning("watchlist_boards_failed", error=str(exc))
            return config
        if not extra:
            return config
        boards = merge_boards(list(config.extra.get("boards", [])), extra)
        logger.info("watchlist_boards_merged", total=len(boards), from_watchlist=len(extra))
        return config.model_copy(update={"extra": {**config.extra, "boards": boards}})

    async def _fetch_source(
        self,
        name: str,
        config: JobSourceConfig,
        params: SourceSearchParams,
        query: SearchQuery,
    ) -> SourceFetchResult:
        started = datetime.now(UTC)
        logger.info("source_search_started", source=name)
        throttle = make_source_throttle(
            self._redis, name, config.rateLimitPerMinute, sleep=self._sleep
        )
        connector = self._registry.connector_with_config(name, config, throttle=throttle)
        try:
            async with asyncio.timeout(self._settings.discovery_source_timeout_seconds):
                raws = await retry_source_call(
                    lambda: connector.search_jobs(params),
                    attempts=self._settings.discovery_retry_attempts,
                    base_delay=self._settings.discovery_retry_base_delay_seconds,
                    max_delay=self._settings.discovery_retry_max_delay_seconds,
                    jitter=self._settings.discovery_retry_jitter_seconds,
                    sleep=self._sleep,
                    source_name=name,
                )
        except TimeoutError:
            message = (
                f"timed out after {self._settings.discovery_source_timeout_seconds:g}s"
            )
            logger.warning("source_search_failed", source=name, error=message)
            return SourceFetchResult(name, error=message)
        except SourceError as exc:
            logger.warning("source_search_failed", source=name, error=exc.message)
            return SourceFetchResult(name, error=exc.message)

        normalized = self._normalizer.normalize_batch(connector, raws)
        kept = self._normalizer.apply_filters(normalized, query)
        elapsed_ms = (datetime.now(UTC) - started).total_seconds() * 1000
        logger.info(
            "source_search_succeeded",
            source=name,
            raw_count=len(raws),
            kept_count=len(kept),
            elapsed_ms=round(elapsed_ms),
        )
        return SourceFetchResult(name, jobs=kept)
