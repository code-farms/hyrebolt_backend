from datetime import UTC, datetime, time

from fastapi import APIRouter

from app.api.deps import (
    ApplicationRepositoryDep,
    CurrentUserDep,
    JobMatchRepositoryDep,
    JobRepositoryDep,
    JobSourceRepositoryDep,
    SavedJobRepositoryDep,
)
from app.models import ApplicationStatus
from app.schemas.dashboard import DashboardStatsOut, SourceOut

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStatsOut)
async def dashboard_stats(
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    matches: JobMatchRepositoryDep,
    saved: SavedJobRepositoryDep,
    applications: ApplicationRepositoryDep,
) -> DashboardStatsOut:
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return DashboardStatsOut(
        newJobsToday=await jobs.count_created_since(today_start),
        excellentMatches=await matches.count_in_score_band(user.id, min_score=85),
        strongMatches=await matches.count_in_score_band(
            user.id, min_score=70, max_score=85
        ),
        savedJobs=await saved.count_for_user(user.id),
        applications=await applications.count_for_user(user.id),
        interviews=await applications.count_for_user(
            user.id, status=ApplicationStatus.INTERVIEW
        ),
    )


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    user: CurrentUserDep, sources: JobSourceRepositoryDep
) -> list[SourceOut]:
    rows = await sources.list_all()
    return [
        SourceOut(name=row.name, displayName=row.displayName, enabled=row.enabled)
        for row in sorted(rows, key=lambda r: r.displayName)
    ]
