from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, JobRepositoryDep
from app.core.exceptions import NotFoundError
from app.schemas.job import JobListOut, JobOut, job_out

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


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, user: CurrentUserDep, jobs: JobRepositoryDep) -> JobOut:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    return job_out(job)
