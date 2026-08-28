"""arq WorkerSettings: the scheduler + worker for the daily agent.

Run: arq app.worker.settings.WorkerSettings
Health: the worker refreshes ``health_check_key`` in Redis every
``health_check_interval`` seconds; the compose healthcheck and
``GET /health`` (worker component) only look for that key.
"""

from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.core.http import close_http_client
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis_client, get_redis_client
from app.db.client import connect_db, disconnect_db
from app.worker.schedule import compute_utc_cron
from app.worker.services import build_agent_tasks
from app.worker.tasks import (
    MAX_TRIES,
    analyze_new_jobs,
    daily_job_search,
    match_jobs,
    send_daily_digest,
)

logger = get_logger(__name__)

_settings = get_settings()
_cron_hour, _cron_minute = compute_utc_cron(_settings.daily_search_time, _settings.timezone)

WORKER_HEALTH_KEY = "arq:queue:health-check"


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(_settings)
    await connect_db()
    # Fail fast on a misconfigured Redis instead of at the first task.
    await get_redis_client(_settings).ping()
    ctx["agent"] = build_agent_tasks(_settings)
    logger.info(
        "worker_started",
        daily_search_time=_settings.daily_search_time,
        timezone=_settings.timezone,
        cron_utc=f"{_cron_hour:02d}:{_cron_minute:02d}",
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    for closer in (close_http_client, close_redis_client, disconnect_db):
        try:
            await closer()
        except Exception as exc:  # noqa: BLE001 - shutdown must run to completion
            logger.warning("worker_shutdown_step_failed", step=closer.__name__, error=str(exc))
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
    max_tries = MAX_TRIES
    retry_jobs = True
    job_timeout = 600
    # The pipeline is four chained tasks; nothing needs more parallelism than this.
    max_jobs = 4
    # arq's default heartbeat is hourly with a 1s TTL margin, which made the
    # container flap "unhealthy" and hid worker outages for up to an hour.
    health_check_interval = 30
    health_check_key = WORKER_HEALTH_KEY
    # Dead-letter record: a permanently failed job's result stays a day
    # (`arq` default is one hour) so it can be inspected after the fact.
    keep_result = 86400
