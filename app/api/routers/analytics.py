from fastapi import APIRouter, Query

from app.api.deps import AnalyticsServiceDep, CurrentUserDep
from app.schemas.analytics import AnalyticsOverviewOut

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverviewOut)
async def analytics_overview(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    range_days: int = Query(default=30, alias="range", ge=1, le=365),
) -> AnalyticsOverviewOut:
    """Whole analytics dashboard for one window (7, 30 or 90 days)."""
    return await service.overview(user, range_days)
