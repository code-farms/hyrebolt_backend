from datetime import UTC, datetime, timedelta

import redis.asyncio as redis

from app.core.config import Settings
from app.models import SearchTrigger
from app.repositories import (
    JobMatchRepository,
    NotificationRepository,
    SearchRunRepository,
)
from app.schemas.agent import AgentScheduleOut, AgentStatusOut
from app.schemas.search import SearchRunOut
from app.worker.schedule import next_scheduled_run_utc

# arq's built-in health check key (default queue name).
_ARQ_HEALTH_KEY = "arq:queue:health-check"


class AgentStatusService:
    def __init__(
        self,
        search_runs: SearchRunRepository,
        matches: JobMatchRepository,
        notifications: NotificationRepository,
        redis_client: redis.Redis,
        settings: Settings,
    ) -> None:
        self._search_runs = search_runs
        self._matches = matches
        self._notifications = notifications
        self._redis = redis_client
        self._settings = settings

    async def status(self) -> AgentStatusOut:
        last_run = await self._search_runs.latest_by_trigger(SearchTrigger.SCHEDULED)
        since = datetime.now(UTC) - timedelta(hours=24)
        worker_health = await self._redis.get(_ARQ_HEALTH_KEY)
        return AgentStatusOut(
            lastRun=(
                SearchRunOut.model_validate(last_run, from_attributes=True)
                if last_run is not None
                else None
            ),
            nextRunAt=next_scheduled_run_utc(
                self._settings.daily_search_time, self._settings.timezone
            ),
            jobsMatchedLast24h=await self._matches.count_updated_since(since),
            notificationsCreatedLast24h=await self._notifications.count_since(since),
            failures=list(last_run.sourcesFailed) if last_run is not None else [],
            errorSummary=last_run.errorSummary if last_run is not None else None,
            workerHealthy=worker_health is not None,
            schedule=AgentScheduleOut(
                dailySearchTime=self._settings.daily_search_time,
                timezone=self._settings.timezone,
            ),
        )
