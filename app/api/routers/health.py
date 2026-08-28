"""Unauthenticated probes.

- GET /health/live — liveness: the process is up (no dependency checks).
- GET /ready      — readiness: Postgres + Redis reachable; 503 otherwise, so
                    a load balancer stops routing here.
- GET /health     — full component report incl. the worker heartbeat; 503
                    when anything is degraded (the frontend status card and
                    external monitors read this)."""

from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


def _with_status(result: HealthResponse, response: Response) -> HealthResponse:
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=HealthResponse)
async def readiness(health_service: HealthServiceDep, response: Response) -> HealthResponse:
    return _with_status(await health_service.get_readiness(), response)


@router.get("/health", response_model=HealthResponse)
async def health(health_service: HealthServiceDep, response: Response) -> HealthResponse:
    return _with_status(await health_service.get_health(), response)
