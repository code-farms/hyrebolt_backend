"""Liveness / readiness / component health (Phase 18).

Three components: Postgres and Redis (the API cannot serve without them) and
the background worker, detected through the heartbeat key arq refreshes
every ``WorkerSettings.health_check_interval`` seconds. Probes run
concurrently, each under its own short timeout, so a hung dependency turns
into a reported error instead of a hung endpoint."""

import asyncio

import redis.asyncio as redis

from app.core.logging import get_logger
from app.db.generated import Prisma
from app.schemas.health import ComponentStatus, HealthResponse

logger = get_logger(__name__)

_UNREACHABLE = "unreachable"
PROBE_TIMEOUT_SECONDS = 2.0
# Must match app.worker.settings.WorkerSettings.health_check_key.
WORKER_HEALTH_KEY = "arq:queue:health-check"
# Components a request cannot be served without; the worker is not one.
READINESS_COMPONENTS = ("postgres", "redis")


class HealthService:
    def __init__(
        self,
        prisma: Prisma,
        redis_client: redis.Redis,
        *,
        expose_details: bool = True,
        probe_timeout: float = PROBE_TIMEOUT_SECONDS,
    ) -> None:
        self._prisma = prisma
        self._redis = redis_client
        # Driver errors embed hosts, ports and sometimes DSNs; /health is
        # public, so production reports only that a component is down.
        self._expose_details = expose_details
        self._probe_timeout = probe_timeout

    def _detail(self, exc: BaseException) -> str:
        if isinstance(exc, TimeoutError):
            return "timed out"
        return str(exc) if self._expose_details else _UNREACHABLE

    async def _probe(self, name: str, coroutine) -> ComponentStatus:  # type: ignore[no-untyped-def]
        try:
            async with asyncio.timeout(self._probe_timeout):
                detail = await coroutine
        except Exception as exc:  # noqa: BLE001 - reported as a component status, not raised
            logger.warning("health_check_failed", component=name, error=str(exc))
            return ComponentStatus(name=name, status="error", detail=self._detail(exc))
        if detail is not None:
            return ComponentStatus(name=name, status="error", detail=detail)
        return ComponentStatus(name=name, status="ok")

    async def _db_probe(self) -> None:
        # Connectivity-only probe, deliberately independent of any business
        # table so schema changes never break readiness.
        await self._prisma.query_raw("SELECT 1")

    async def _redis_probe(self) -> None:
        await self._redis.ping()

    async def _worker_probe(self) -> str | None:
        alive = await self._redis.get(WORKER_HEALTH_KEY)
        return None if alive else "no worker heartbeat"

    async def check_db(self) -> ComponentStatus:
        return await self._probe("postgres", self._db_probe())

    async def check_redis(self) -> ComponentStatus:
        return await self._probe("redis", self._redis_probe())

    async def check_worker(self) -> ComponentStatus:
        return await self._probe("worker", self._worker_probe())

    async def get_health(self) -> HealthResponse:
        """Everything, for dashboards: degraded when any component is down."""
        components = list(
            await asyncio.gather(self.check_db(), self.check_redis(), self.check_worker())
        )
        overall = "ok" if all(c.status == "ok" for c in components) else "degraded"
        return HealthResponse(status=overall, components=components)

    async def get_readiness(self) -> HealthResponse:
        """Can this process serve requests? Only the hard dependencies count."""
        components = list(await asyncio.gather(self.check_db(), self.check_redis()))
        overall = "ok" if all(c.status == "ok" for c in components) else "degraded"
        return HealthResponse(status=overall, components=components)
