from typing import Any

from app.db.generated.models import Company
from app.repositories.base import BaseRepository
from app.sources.models import CompanyMetadata
from app.utils.normalization import normalize_company


def _viewer_include(user_id: str | None) -> dict[str, Any]:
    if user_id is None:
        return {}
    return {"watchlistEntries": {"where": {"userId": user_id}}}


class CompanyRepository(BaseRepository):
    async def upsert_by_normalized_name(
        self, name: str, metadata: CompanyMetadata | None = None
    ) -> Company:
        """Resolves the company row for a raw name. Metadata (Phase 13) only
        ever fills columns that are still null: a later source never
        overwrites what an earlier one — or the user — recorded."""
        normalized = normalize_company(name)
        row = await self._prisma.company.upsert(
            where={"normalizedName": normalized},
            data={
                "create": {"name": name.strip(), "normalizedName": normalized},
                # Never clobber the stored display name with a later variant.
                "update": {},
            },
        )
        if metadata is None:
            return row
        fill = {
            key: value
            for key, value in metadata.model_dump(exclude_none=True).items()
            if getattr(row, key, None) is None
        }
        if not fill:
            return row
        return await self._prisma.company.update(where={"id": row.id}, data=fill)  # type: ignore[arg-type]

    async def get_by_id(self, company_id: str, *, viewer_id: str | None = None) -> Company | None:
        return await self._prisma.company.find_unique(
            where={"id": company_id},
            include=_viewer_include(viewer_id) or None,  # type: ignore[arg-type]
        )

    async def search(
        self, query: str | None, *, viewer_id: str, limit: int, offset: int
    ) -> tuple[list[Company], int]:
        where: dict[str, Any] = {}
        if query:
            where["name"] = {"contains": query.strip(), "mode": "insensitive"}
        rows = await self._prisma.company.find_many(
            where=where,  # type: ignore[arg-type]
            order={"name": "asc"},
            take=limit,
            skip=offset,
            include=_viewer_include(viewer_id),  # type: ignore[arg-type]
        )
        total = await self._prisma.company.count(where=where)  # type: ignore[arg-type]
        return rows, total

    async def update_metadata(self, company_id: str, data: dict[str, Any]) -> Company:
        return await self._prisma.company.update(
            where={"id": company_id},
            data=data,  # type: ignore[arg-type]
        )

    async def list_watched_careers_urls(self, *, limit: int = 200) -> list[tuple[str, str]]:
        """(name, careersUrl) for every company on at least one watchlist that
        has a careers URL — the input for watchlist-driven board discovery."""
        rows = await self._prisma.company.find_many(
            where={"careersUrl": {"not": None}, "watchlistEntries": {"some": {}}},  # type: ignore[typeddict-item]
            order={"name": "asc"},
            take=limit,
        )
        return [(row.name, row.careersUrl) for row in rows if row.careersUrl]
