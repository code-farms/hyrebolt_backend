from app.db.generated import Json
from app.db.generated.models import JobSource
from app.repositories.base import BaseRepository


class JobSourceRepository(BaseRepository):
    async def get_by_name(self, name: str) -> JobSource | None:
        return await self._prisma.jobsource.find_unique(where={"name": name})

    async def upsert_by_name(
        self,
        name: str,
        *,
        display_name: str,
        base_url: str | None = None,
        enabled: bool = False,
        requires_auth: bool = False,
        rate_limit_per_minute: int | None = None,
        capabilities: list[str] | None = None,
    ) -> JobSource:
        capabilities_json = Json(capabilities or [])
        return await self._prisma.jobsource.upsert(
            where={"name": name},
            data={
                "create": {
                    "name": name,
                    "displayName": display_name,
                    "baseUrl": base_url,
                    "enabled": enabled,
                    "requiresAuth": requires_auth,
                    "rateLimitPerMinute": rate_limit_per_minute,
                    "capabilities": capabilities_json,
                },
                "update": {
                    "displayName": display_name,
                    "baseUrl": base_url,
                    "requiresAuth": requires_auth,
                    "rateLimitPerMinute": rate_limit_per_minute,
                    "capabilities": capabilities_json,
                    # `enabled` is deliberately not updated: it's operator
                    # state, and re-seeding must never flip a live source off.
                },
            },
        )
