import redis.asyncio as redis

from app.db.generated import Prisma
from app.schemas.health import ComponentStatus, HealthResponse


class HealthService:
    def __init__(self, prisma: Prisma, redis_client: redis.Redis) -> None:
        self._prisma = prisma
        self._redis = redis_client

    async def check_db(self) -> ComponentStatus:
        try:
            # Connectivity-only probe, deliberately independent of any
            # business table so schema changes never break readiness.
            await self._prisma.query_raw("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - reported as a component status, not raised
            return ComponentStatus(name="postgres", status="error", detail=str(exc))
        return ComponentStatus(name="postgres", status="ok")

    async def check_redis(self) -> ComponentStatus:
        try:
            await self._redis.ping()
        except Exception as exc:  # noqa: BLE001 - reported as a component status, not raised
            return ComponentStatus(name="redis", status="error", detail=str(exc))
        return ComponentStatus(name="redis", status="ok")

    async def get_health(self) -> HealthResponse:
        components = [await self.check_db(), await self.check_redis()]
        overall = "ok" if all(c.status == "ok" for c in components) else "degraded"
        return HealthResponse(status=overall, components=components)
