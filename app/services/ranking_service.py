from app.db.generated.models import JobMatch, User
from app.repositories import JobMatchRepository


class RankingService:
    """Phase 8: rank by the stored deterministic overallScore (fully
    interpretable — the component scores explain every position). Phase 16
    layers preference/freshness/feedback signals on top."""

    def __init__(self, matches: JobMatchRepository) -> None:
        self._matches = matches

    async def recommended(
        self, user: User, *, limit: int, offset: int, min_score: float
    ) -> tuple[list[JobMatch], int]:
        return await self._matches.list_ranked_for_user(
            user.id, limit=limit, offset=offset, min_score=min_score
        )
