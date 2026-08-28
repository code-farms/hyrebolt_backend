from fastapi import APIRouter, Query

from app.api.deps import (
    CurrentUserDep,
    DiscoveryServiceDep,
    SearchRunRepositoryDep,
    rate_limit,
)
from app.core.exceptions import NotFoundError
from app.db.generated.models import SearchRun
from app.models import SearchTrigger
from app.schemas.search import SearchQuery, SearchRunListOut, SearchRunOut

router = APIRouter(prefix="/api/v1", tags=["search"])


def _run_out(run: SearchRun) -> SearchRunOut:
    out = SearchRunOut.model_validate(run, from_attributes=True)
    if run.userId is None:
        # Scheduled runs aggregate every user's target roles/locations into
        # one query; that union is not any single caller's to see.
        out.query = None
    return out


@router.post(
    "/search",
    response_model=SearchRunOut,
    dependencies=[rate_limit("search", "search_rate_limit_per_minute")],
)
async def run_search(
    payload: SearchQuery, user: CurrentUserDep, discovery: DiscoveryServiceDep
) -> SearchRunOut:
    # Synchronous in-request for Phase 5; Phase 9 moves execution to workers
    # and this returns a PENDING run of the same shape.
    run = await discovery.run_search(
        user_id=user.id, query=payload, trigger=SearchTrigger.MANUAL
    )
    return _run_out(run)


@router.get("/search-runs", response_model=SearchRunListOut)
async def list_search_runs(
    user: CurrentUserDep,
    runs: SearchRunRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SearchRunListOut:
    rows, total = await runs.list_visible_to(user.id, limit=limit, offset=offset)
    return SearchRunListOut(
        items=[_run_out(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/search-runs/{run_id}", response_model=SearchRunOut)
async def get_search_run(
    run_id: str, user: CurrentUserDep, runs: SearchRunRepositoryDep
) -> SearchRunOut:
    run = await runs.get_by_id(run_id)
    # 404 for foreign runs too: don't leak existence.
    if run is None or run.userId not in (None, user.id):
        raise NotFoundError("Search run not found.")
    return _run_out(run)
