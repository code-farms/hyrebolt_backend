from typing import Any

from app.db.generated.models import CompanyWatchlist
from app.repositories.base import BaseRepository

_INCLUDE = {"company": True}

# Prisma orders enums alphabetically, so sort in Python: HIGH, MEDIUM, LOW.
_PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


class CompanyWatchlistRepository(BaseRepository):
    async def list_for_user(self, user_id: str) -> list[CompanyWatchlist]:
        rows = await self._prisma.companywatchlist.find_many(
            where={"userId": user_id},
            include=_INCLUDE,  # type: ignore[arg-type]
        )
        rows.sort(
            key=lambda row: (
                _PRIORITY_ORDER.get(str(row.priority), 9),
                (row.company.name if row.company else "").casefold(),
            )
        )
        return rows

    async def get_for_user(self, entry_id: str, user_id: str) -> CompanyWatchlist | None:
        row = await self._prisma.companywatchlist.find_unique(
            where={"id": entry_id},
            include=_INCLUDE,  # type: ignore[arg-type]
        )
        if row is None or row.userId != user_id:
            return None
        return row

    async def get_by_user_company(
        self, user_id: str, company_id: str
    ) -> CompanyWatchlist | None:
        return await self._prisma.companywatchlist.find_unique(
            where={"userId_companyId": {"userId": user_id, "companyId": company_id}},
            include=_INCLUDE,  # type: ignore[arg-type]
        )

    async def create(
        self, user_id: str, company_id: str, data: dict[str, Any]
    ) -> CompanyWatchlist:
        return await self._prisma.companywatchlist.create(
            data={"userId": user_id, "companyId": company_id, **data},  # type: ignore[typeddict-item]
            include=_INCLUDE,  # type: ignore[arg-type]
        )

    async def update(self, entry_id: str, data: dict[str, Any]) -> CompanyWatchlist:
        return await self._prisma.companywatchlist.update(
            where={"id": entry_id},
            data=data,  # type: ignore[arg-type]
            include=_INCLUDE,  # type: ignore[arg-type]
        )

    async def delete(self, entry_id: str) -> None:
        await self._prisma.companywatchlist.delete(where={"id": entry_id})

    async def list_all_preferred_roles(self) -> list[str]:
        """Every user's watchlist preferred roles, deduped in first-seen order —
        folded into the daily aggregate search so watched boards' jobs pass the
        connector keyword filter."""
        rows = await self._prisma.companywatchlist.find_many(order={"createdAt": "asc"})
        return list(dict.fromkeys(role for row in rows for role in row.preferredRoles if role))
