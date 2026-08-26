from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.ai import LLMError
from app.api.deps import (
    CurrentUserDep,
    JobRepositoryDep,
    ResumeAnalysisServiceDep,
    ResumeGapServiceDep,
    ResumeServiceDep,
    SettingsDep,
    rate_limit,
)
from app.core.exceptions import DependencyUnavailableError, InvalidInputError, NotFoundError
from app.db.generated.models import Job
from app.repositories import JobRepository
from app.schemas.resume import (
    ResumeGapOut,
    ResumeListOut,
    ResumeOut,
    ResumeVersionDetailOut,
    ResumeVersionOut,
    version_detail_out,
    version_out,
)

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"])

_CHUNK = 1 << 20


async def _read_limited(file: UploadFile, max_mb: int) -> bytes:
    """Reads the upload in chunks and stops at the cap — Content-Length is
    client-supplied and never trusted."""
    limit = max_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise InvalidInputError(f"File exceeds the {max_mb} MB limit.")
        chunks.append(chunk)
    if total == 0:
        raise InvalidInputError("The uploaded file is empty.")
    return b"".join(chunks)


async def _require_job(jobs: JobRepository, job_id: str) -> Job:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    return job


# NOTE: static paths (/gap, /versions) must be declared before /{resume_id}.


@router.get("", response_model=ResumeListOut)
async def list_resumes(user: CurrentUserDep, service: ResumeServiceDep) -> ResumeListOut:
    return await service.list(user)


@router.post(
    "",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("resume_upload", "resume_upload_rate_limit_per_minute")],
)
async def upload_resume(
    user: CurrentUserDep,
    service: ResumeServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=200)] = None,
    resumeId: Annotated[str | None, Form()] = None,
) -> ResumeOut:
    data = await _read_limited(file, settings.resume_max_upload_mb)
    return await service.upload(
        user,
        filename=file.filename or "",
        data=data,
        title=title.strip() if title and title.strip() else None,
        resume_id=resumeId or None,
    )


@router.get("/gap/{job_id}", response_model=ResumeGapOut)
async def selected_resume_gap(
    job_id: str,
    user: CurrentUserDep,
    service: ResumeServiceDep,
    gap: ResumeGapServiceDep,
    jobs: JobRepositoryDep,
    force: bool = Query(default=False),
) -> ResumeGapOut:
    version = await service.selected_version(user)
    if version is None:
        raise NotFoundError("No resume selected.")
    job = await _require_job(jobs, job_id)
    return await gap.analyze(user, version, job, force=force)


@router.get("/versions/{version_id}", response_model=ResumeVersionDetailOut)
async def get_version(
    version_id: str, user: CurrentUserDep, service: ResumeServiceDep
) -> ResumeVersionDetailOut:
    return version_detail_out(await service.get_version(user, version_id))


@router.get("/versions/{version_id}/download")
async def download_version(
    version_id: str, user: CurrentUserDep, service: ResumeServiceDep
) -> FileResponse:
    path, version = await service.file_path(user, version_id)
    return FileResponse(path, media_type=version.mimeType, filename=version.fileName)


@router.post("/versions/{version_id}/analyze", response_model=ResumeVersionOut)
async def analyze_version(
    version_id: str,
    user: CurrentUserDep,
    service: ResumeServiceDep,
    analysis: ResumeAnalysisServiceDep,
    force: bool = Query(default=False),
) -> ResumeVersionOut:
    version = await service.get_version(user, version_id)
    try:
        await analysis.analyze_version(version, force=force)
    except LLMError as exc:
        raise DependencyUnavailableError("Resume analysis is unavailable right now.") from exc
    return version_out(await service.get_version(user, version_id))


@router.get("/versions/{version_id}/gap/{job_id}", response_model=ResumeGapOut)
async def version_gap(
    version_id: str,
    job_id: str,
    user: CurrentUserDep,
    service: ResumeServiceDep,
    gap: ResumeGapServiceDep,
    jobs: JobRepositoryDep,
    force: bool = Query(default=False),
) -> ResumeGapOut:
    version = await service.get_version(user, version_id)
    job = await _require_job(jobs, job_id)
    return await gap.analyze(user, version, job, force=force)


@router.get("/{resume_id}", response_model=ResumeOut)
async def get_resume(resume_id: str, user: CurrentUserDep, service: ResumeServiceDep) -> ResumeOut:
    return await service.get(user, resume_id)


@router.post("/{resume_id}/select", response_model=ResumeOut)
async def select_resume(
    resume_id: str, user: CurrentUserDep, service: ResumeServiceDep
) -> ResumeOut:
    return await service.select(user, resume_id)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: str, user: CurrentUserDep, service: ResumeServiceDep) -> Response:
    await service.delete(user, resume_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
