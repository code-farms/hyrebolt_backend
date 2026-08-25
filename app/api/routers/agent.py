from fastapi import APIRouter

from app.api.deps import AgentStatusServiceDep, CurrentUserDep
from app.schemas.agent import AgentStatusOut

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.get("/status", response_model=AgentStatusOut)
async def agent_status(user: CurrentUserDep, service: AgentStatusServiceDep) -> AgentStatusOut:
    return await service.status()
