from fastapi import APIRouter, Query, Response, status

from app.api.deps import CompanyServiceDep, CurrentUserDep
from app.schemas.company import (
    CompanyListOut,
    CompanyMetadataIn,
    CompanyOut,
    WatchlistCreateIn,
    WatchlistEntryOut,
    WatchlistListOut,
    WatchlistUpdateIn,
)
from app.schemas.job import JobListOut, job_out

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


# NOTE: the static /watchlist routes must be declared before /{company_id}.


@router.get("/watchlist", response_model=WatchlistListOut)
async def list_watchlist(user: CurrentUserDep, service: CompanyServiceDep) -> WatchlistListOut:
    return await service.list_watchlist(user)


@router.get("/watchlist/jobs", response_model=JobListOut)
async def list_watchlist_jobs(
    user: CurrentUserDep,
    service: CompanyServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    rows, total = await service.recent_watchlist_jobs(user, limit=limit, offset=offset)
    return JobListOut(items=[job_out(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("/watchlist", response_model=WatchlistEntryOut, status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    payload: WatchlistCreateIn, user: CurrentUserDep, service: CompanyServiceDep
) -> WatchlistEntryOut:
    return await service.add_to_watchlist(user, payload)


@router.patch("/watchlist/{entry_id}", response_model=WatchlistEntryOut)
async def update_watchlist_entry(
    entry_id: str,
    payload: WatchlistUpdateIn,
    user: CurrentUserDep,
    service: CompanyServiceDep,
) -> WatchlistEntryOut:
    return await service.update_entry(user, entry_id, payload.to_update())


@router.delete("/watchlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_watchlist_entry(
    entry_id: str, user: CurrentUserDep, service: CompanyServiceDep
) -> Response:
    await service.remove_entry(user, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=CompanyListOut)
async def list_companies(
    user: CurrentUserDep,
    service: CompanyServiceDep,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CompanyListOut:
    return await service.list_companies(user, query=q, limit=limit, offset=offset)


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: str, user: CurrentUserDep, service: CompanyServiceDep
) -> CompanyOut:
    return await service.get_company(user, company_id)


@router.get("/{company_id}/jobs", response_model=JobListOut)
async def list_company_jobs(
    company_id: str,
    user: CurrentUserDep,
    service: CompanyServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    rows, total = await service.list_company_jobs(user, company_id, limit=limit, offset=offset)
    return JobListOut(items=[job_out(row) for row in rows], total=total, limit=limit, offset=offset)


@router.patch("/{company_id}", response_model=CompanyOut)
async def update_company_metadata(
    company_id: str,
    payload: CompanyMetadataIn,
    user: CurrentUserDep,
    service: CompanyServiceDep,
) -> CompanyOut:
    return await service.update_metadata(user, company_id, payload.to_update())
