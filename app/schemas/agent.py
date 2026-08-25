# camelCase wire contract.
from datetime import datetime

from pydantic import BaseModel

from app.schemas.search import SearchRunOut


class AgentScheduleOut(BaseModel):
    dailySearchTime: str
    timezone: str


class AgentStatusOut(BaseModel):
    lastRun: SearchRunOut | None
    nextRunAt: datetime
    jobsMatchedLast24h: int
    notificationsCreatedLast24h: int
    failures: list[str]
    errorSummary: str | None
    workerHealthy: bool
    schedule: AgentScheduleOut
