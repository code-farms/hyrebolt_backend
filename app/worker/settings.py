"""arq WorkerSettings: the scheduler + worker for the daily agent.

Run: arq app.worker.settings.WorkerSettings
Health check: arq --check app.worker.settings.WorkerSettings
"""

from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.core.http import close_http_client
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis_client
from app.db.client import connect_db, disconnect_db
from app.worker.schedule import compute_utc_cron
from app.worker.services import build_agent_tasks
from app.worker.tasks import (
    analyze_new_jobs,
    daily_job_search,
    match_jobs,
    send_daily_digest,
)

logger = get_logger(__name__)

_settings = get_settings()
_cron_hour, _cron_minute = compute_utc_cron(_settings.daily_search_time, _settings.timezone)


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(_settings)
    await connect_db()
    ctx["agent"] = build_agent_tasks(_settings)
    logger.info(
        "worker_started",
        daily_search_time=_settings.daily_search_time,
        timezone=_settings.timezone,
        cron_utc=f"{_cron_hour:02d}:{_cron_minute:02d}",
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await close_http_client()
    await close_redis_client()
    await disconnect_db()
    logger.info("worker_stopped")


class WorkerSettings:
    # arq settings classes use class attributes by design.
    functions = (daily_job_search, analyze_new_jobs, match_jobs, send_daily_digest)
    cron_jobs = (
        cron(
            daily_job_search,
            hour=_cron_hour,
            minute=_cron_minute,
            name="daily_job_search_cron",
        ),
    )
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_tries = 3
    retry_jobs = True
    job_timeout = 600
