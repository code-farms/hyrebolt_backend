from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import (
    ApplicationServiceDep,
    CurrentUserDep,
    JobRepositoryDep,
)
from app.core.exceptions import NotFoundError
from app.models import ApplicationStatus
from app.schemas.application import (
    ApplicationListOut,
    ApplicationOut,
    ApplicationStatsOut,
    DetailsIn,
    EventIn,
    StatusIn,
    TrackJobIn,
    application_out,
)

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])


@router.post("", response_model=ApplicationOut)
async def track_job(
    payload: TrackJobIn,
    user: CurrentUserDep,
    service: ApplicationServiceDep,
    jobs: JobRepositoryDep,
) -> ApplicationOut:
    job = await jobs.get_by_id(payload.jobId)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    application = await service.track_job(user, payload.jobId, payload.status)
    return application_out(application)


@router.get("", response_model=ApplicationListOut)
async def list_applications(
    user: CurrentUserDep,
    service: ApplicationServiceDep,
    status: Annotated[ApplicationStatus | None, Query()] = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApplicationListOut:
    rows, total = await service.list(user, status=status, limit=limit, offset=offset)
    return ApplicationListOut(
        items=[application_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=ApplicationStatsOut)
async def application_stats(
    user: CurrentUserDep, service: ApplicationServiceDep
) -> ApplicationStatsOut:
    return ApplicationStatsOut(**await service.stats(user))


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: str, user: CurrentUserDep, service: ApplicationServiceDep
) -> ApplicationOut:
    return application_out(await service.get(user, application_id))


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update_details(
    application_id: str,
    payload: DetailsIn,
    user: CurrentUserDep,
    service: ApplicationServiceDep,
) -> ApplicationOut:
    application = await service.update_details(user, application_id, payload.to_update())
    return application_out(application)


@router.post("/{application_id}/status", response_model=ApplicationOut)
async def update_status(
    application_id: str,
    payload: StatusIn,
    user: CurrentUserDep,
    service: ApplicationServiceDep,
) -> ApplicationOut:
    application = await service.update_status(
        user, application_id, payload.status, payload.note
    )
    return application_out(application)


@router.post("/{application_id}/events", response_model=ApplicationOut)
async def add_event(
    application_id: str,
    payload: EventIn,
    user: CurrentUserDep,
    service: ApplicationServiceDep,
) -> ApplicationOut:
    application = await service.add_event(
        user, application_id, title=payload.title, notes=payload.notes
    )
    return application_out(application)
