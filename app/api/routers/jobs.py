from fastapi import APIRouter, Query

from app.api.deps import (
    CandidateMatchingServiceDep,
    CurrentUserDep,
    JobAnalysisServiceDep,
    JobRepositoryDep,
    RankingServiceDep,
    SettingsDep,
)
from app.core.exceptions import NotFoundError
from app.schemas.analysis import JobAnalysisOut
from app.schemas.job import JobListOut, JobOut, analysis_out, job_out
from app.schemas.match import (
    FeedbackIn,
    MatchOut,
    RecommendedListOut,
    match_out,
    recommended_out,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("", response_model=JobListOut)
async def list_jobs(
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    rows, total = await jobs.list_active_with_listings(limit=limit, offset=offset)
    return JobListOut(
        items=[job_out(row) for row in rows], total=total, limit=limit, offset=offset
    )


# NOTE: static paths must be declared before the /{job_id} routes.
@router.get("/recommended", response_model=RecommendedListOut)
async def recommended_jobs(
    user: CurrentUserDep,
    matching: CandidateMatchingServiceDep,
    ranking: RankingServiceDep,
    settings: SettingsDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    minScore: float = Query(default=0, ge=0, le=100),
) -> RecommendedListOut:
    # Score any not-yet-matched jobs first (bounded; Phase 9 moves this batch
    # to the background workers), then return the ranked list.
    await matching.ensure_matches_for_user(user, limit=settings.match_batch_limit)
    rows, total = await ranking.recommended(
        user, limit=limit, offset=offset, min_score=minScore
    )
    return RecommendedListOut(
        items=[recommended_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, user: CurrentUserDep, jobs: JobRepositoryDep) -> JobOut:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    return job_out(job)


@router.post("/{job_id}/analyze", response_model=JobAnalysisOut)
async def analyze_job(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    analysis_service: JobAnalysisServiceDep,
) -> JobAnalysisOut:
    """Run (or return the cached) AI analysis for a job."""
    job = await jobs.get_by_id(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    row = await analysis_service.analyze_job(job)
    return analysis_out(row)


@router.get("/{job_id}/match", response_model=MatchOut)
async def get_job_match(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    matching: CandidateMatchingServiceDep,
) -> MatchOut:
    """Compute (or return the cached) match between the caller and a job."""
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    match = await matching.match_job(user, job)
    return match_out(match)


@router.post("/{job_id}/feedback", response_model=MatchOut)
async def job_feedback(
    job_id: str,
    payload: FeedbackIn,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    matching: CandidateMatchingServiceDep,
) -> MatchOut:
    job = await jobs.get_by_id(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    match = await matching.record_feedback(user, job, payload.to_enum())
    return match_out(match)
