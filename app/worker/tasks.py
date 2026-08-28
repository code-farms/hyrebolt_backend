"""The four Phase 9 agent tasks.

Idempotency model:
- daily_job_search: Redis date-key guard (SET NX) — one run per calendar day
  even across worker restarts/retries; discovery itself is duplicate-safe.
- analyze_new_jobs: JobAnalysis.jobId unique + promptVersion (Phase 7).
- match_jobs: JobMatch @@unique([userId, jobId]) + scoringVersion (Phase 8).
- send_daily_digest: Notification.dedupeKey unique ("digest:{userId}:{date}").
Chaining uses deterministic arq job ids so a re-enqueued day cannot fan out
twice. Every task logs structured events; arq retries failures (max_tries),
and the final failure is logged as task_failed_permanently (the arq result
key in Redis is the dead-letter record)."""

from datetime import UTC, date, datetime
from typing import Any

import redis.asyncio as redis

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import SearchTrigger
from app.repositories import CompanyWatchlistRepository, ProfileRepository, UserRepository
from app.schemas.search import SearchQuery
from app.services.candidate_matching_service import CandidateMatchingService
from app.services.daily_digest_service import DailyDigestService
from app.services.discovery_service import DiscoveryService
from app.services.job_analysis_service import JobAnalysisService

logger = get_logger(__name__)


class AgentTasks:
    """Injectable core so unit tests run against fakes; the arq wrappers at
    the bottom of this module only pull this object out of ctx."""

    def __init__(
        self,
        *,
        discovery: DiscoveryService,
        analysis: JobAnalysisService,
        matching: CandidateMatchingService,
        digest: DailyDigestService,
        users: UserRepository,
        profiles: ProfileRepository,
        redis_client: redis.Redis,
        settings: Settings,
        watchlists: CompanyWatchlistRepository | None = None,
    ) -> None:
        self._discovery = discovery
        self._analysis = analysis
        self._matching = matching
        self._digest = digest
        self._users = users
        self._profiles = profiles
        self._redis = redis_client
        self._settings = settings
        self._watchlists = watchlists

    async def run_daily_search(self, *, today: date | None = None) -> dict[str, Any]:
        run_date = (today or datetime.now(UTC).date()).isoformat()
        acquired = await self._redis.set(
            f"agent:daily_search:{run_date}", "1", nx=True, ex=86400
        )
        if not acquired:
            logger.info("daily_search_skipped_duplicate", date=run_date)
            return {"executed": False, "date": run_date}

        query = await self.build_aggregate_query()
        run = await self._discovery.run_search(
            user_id=None, query=query, trigger=SearchTrigger.SCHEDULED
        )
        logger.info(
            "daily_search_completed",
            date=run_date,
            run_id=run.id,
            status=str(run.status),
            jobs_new=run.jobsNew,
            jobs_duplicate=run.jobsDuplicate,
        )
        return {"executed": True, "date": run_date, "run_id": run.id}

    async def build_aggregate_query(self) -> SearchQuery:
        """One SCHEDULED search covering every active user's targets."""
        roles: list[str] = []
        locations: list[str] = []
        for user in await self._users.list_active():
            profile = await self._profiles.get_by_user_id(user.id)
            if profile is None:
                continue
            roles.extend(profile.targetRoles)
            locations.extend(profile.preferredLocations)
        if self._watchlists is not None:
            # Phase 13: watched boards are keyword-filtered by the connector, so
            # the roles users want at those companies must be in the query.
            roles.extend(await self._watchlists.list_all_preferred_roles())
        return SearchQuery(
            targetRoles=list(dict.fromkeys(roles))[:20],
            locations=list(dict.fromkeys(locations))[:20],
            limitPerSource=self._settings.discovery_max_jobs_per_source,
        )

    async def analyze_new_jobs(self) -> int:
        analyzed = await self._analysis.analyze_unanalyzed(
            limit=self._settings.agent_analyze_batch
        )
        logger.info("agent_analyze_completed", analyzed=analyzed)
        return analyzed

    async def match_jobs(self) -> int:
        total = 0
        for user in await self._users.list_active():
            try:
                total += await self._matching.ensure_matches_for_user(
                    user, limit=self._settings.agent_match_batch
                )
            except Exception as exc:  # noqa: BLE001 - one user must not sink the batch
                logger.warning("agent_match_user_failed", user_id=user.id, error=str(exc))
        logger.info("agent_match_completed", matched=total)
        return total

    async def send_daily_digest(self, *, today: date | None = None) -> dict[str, int]:
        run_date = today or datetime.now(UTC).date()
        created = 0
        deduped = 0
        failed = 0
        for user in await self._users.list_active():
            try:
                outcomes = await self._digest.send_for_user(user, run_date)
            except Exception as exc:  # noqa: BLE001 - one user must not sink the batch
                logger.warning("agent_digest_user_failed", user_id=user.id, error=str(exc))
                failed += 1
                continue
            created += sum(1 for o in outcomes.values() if o in ("created", "sent"))
            deduped += sum(1 for o in outcomes.values() if o == "deduped")
            failed += sum(1 for o in outcomes.values() if o == "failed")
        logger.info(
            "agent_digest_completed",
            date=run_date.isoformat(),
            created=created,
            skipped=deduped,
            failed=failed,
        )
        return {"created": created, "skipped": deduped, "failed": failed}


# Shared with WorkerSettings.max_tries: arq's job context exposes `job_try` but
# not the configured maximum, so the dead-letter decision reads this constant.
MAX_TRIES = 3


def _log_final_failure(ctx: dict[str, Any], task: str, exc: Exception) -> None:
    job_try = int(ctx.get("job_try") or 1)
    if job_try >= MAX_TRIES:
        # Dead letter: the traceback is captured here because this is the last
        # time anyone will see this failure (see WorkerSettings.keep_result).
        logger.error(
            "task_failed_permanently",
            task=task,
            job_id=ctx.get("job_id"),
            tries=job_try,
            error=str(exc),
            exc_info=exc,
        )
    else:
        logger.warning(
            "task_failed_will_retry",
            task=task,
            job_id=ctx.get("job_id"),
            try_number=job_try,
            error=str(exc),
        )


async def daily_job_search(ctx: dict[str, Any]) -> dict[str, Any]:
    agent: AgentTasks = ctx["agent"]
    try:
        result = await agent.run_daily_search()
    except Exception as exc:
        _log_final_failure(ctx, "daily_job_search", exc)
        raise
    if result["executed"]:
        await ctx["redis"].enqueue_job(
            "analyze_new_jobs", _job_id=f"analyze:{result['date']}"
        )
    return result


async def analyze_new_jobs(ctx: dict[str, Any]) -> int:
    agent: AgentTasks = ctx["agent"]
    try:
        analyzed = await agent.analyze_new_jobs()
    except Exception as exc:
        _log_final_failure(ctx, "analyze_new_jobs", exc)
        raise
    today = datetime.now(UTC).date().isoformat()
    await ctx["redis"].enqueue_job("match_jobs", _job_id=f"match:{today}")
    return analyzed


async def match_jobs(ctx: dict[str, Any]) -> int:
    agent: AgentTasks = ctx["agent"]
    try:
        matched = await agent.match_jobs()
    except Exception as exc:
        _log_final_failure(ctx, "match_jobs", exc)
        raise
    today = datetime.now(UTC).date().isoformat()
    await ctx["redis"].enqueue_job("send_daily_digest", _job_id=f"digest:{today}")
    return matched


async def send_daily_digest(ctx: dict[str, Any]) -> dict[str, int]:
    agent: AgentTasks = ctx["agent"]
    try:
        return await agent.send_daily_digest()
    except Exception as exc:
        _log_final_failure(ctx, "send_daily_digest", exc)
        raise
