from fastapi import APIRouter

from app.api.deps import (
    ApplicationAssistantServiceDep,
    CurrentUserDep,
    JobRepositoryDep,
    rate_limit,
)
from app.core.exceptions import NotFoundError
from app.db.generated.models import Job
from app.models import ApplicationDraftKind
from app.repositories import JobRepository
from app.schemas.assistant import AssistantOut, DraftOut, GenerateIn, SaveDraftIn

# Drafts only. There is deliberately no endpoint that submits an application.
router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


async def _require_job(jobs: JobRepository, job_id: str) -> Job:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    return job


@router.get("/{job_id}", response_model=AssistantOut)
async def get_assistant(
    job_id: str,
    user: CurrentUserDep,
    service: ApplicationAssistantServiceDep,
    jobs: JobRepositoryDep,
) -> AssistantOut:
    return await service.get(user, await _require_job(jobs, job_id))


@router.post(
    "/{job_id}/generate",
    response_model=AssistantOut,
    dependencies=[rate_limit("assistant", "assistant_rate_limit_per_minute")],
)
async def generate_drafts(
    job_id: str,
    payload: GenerateIn,
    user: CurrentUserDep,
    service: ApplicationAssistantServiceDep,
    jobs: JobRepositoryDep,
) -> AssistantOut:
    job = await _require_job(jobs, job_id)
    return await service.generate(user, job, kinds=payload.kinds, force=payload.force)


@router.put("/{job_id}/drafts/{kind}", response_model=DraftOut)
async def save_draft(
    job_id: str,
    kind: ApplicationDraftKind,
    payload: SaveDraftIn,
    user: CurrentUserDep,
    service: ApplicationAssistantServiceDep,
    jobs: JobRepositoryDep,
) -> DraftOut:
    job = await _require_job(jobs, job_id)
    return await service.save(user, job, kind, payload.content)
