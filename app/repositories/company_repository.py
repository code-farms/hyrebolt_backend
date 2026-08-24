from app.db.generated.models import Company
from app.repositories.base import BaseRepository
from app.utils.normalization import normalize_company


class CompanyRepository(BaseRepository):
    async def upsert_by_normalized_name(self, name: str) -> Company:
        normalized = normalize_company(name)
        return await self._prisma.company.upsert(
            where={"normalizedName": normalized},
            data={
                "create": {"name": name.strip(), "normalizedName": normalized},
                # Never clobber the stored display name with a later variant.
                "update": {},
            },
        )
