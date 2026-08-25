# camelCase wire contract.
from pydantic import BaseModel


class DashboardStatsOut(BaseModel):
    newJobsToday: int
    excellentMatches: int  # score >= 85
    strongMatches: int  # 70 <= score < 85
    savedJobs: int
    applications: int
    interviews: int


class SourceOut(BaseModel):
    name: str
    displayName: str
    enabled: bool
