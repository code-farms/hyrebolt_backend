# camelCase wire contract, mirrored by the frontend zod schemas (Phase 11).
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models import SearchRunStatus, SearchTrigger


class ExperienceFilter(BaseModel):
    min: float | None = Field(default=None, ge=0, le=60)
    max: float | None = Field(default=None, ge=0, le=60)


class SalaryFilter(BaseModel):
    min: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class SearchQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=20)
    targetRoles: list[str] = Field(default_factory=list, max_length=20)
    locations: list[str] = Field(default_factory=list, max_length=20)
    remote: bool | None = None  # None = no constraint
    experience: ExperienceFilter | None = None
    salary: SalaryFilter | None = None
    datePosted: int | None = Field(default=None, ge=1, le=90)  # days back
    companies: list[str] = Field(default_factory=list, max_length=50)
    sources: list[str] | None = None  # None = all enabled sources
    limitPerSource: int | None = Field(default=None, ge=1, le=200)


class SearchRunOut(BaseModel):
    """jobsFound = jobsNew + jobsDuplicate: jobs that survived normalization
    and filters and entered deduplication."""

    id: str
    trigger: SearchTrigger
    status: SearchRunStatus
    query: dict[str, Any] | None
    startedAt: datetime | None
    completedAt: datetime | None
    sourcesAttempted: list[str]
    sourcesSucceeded: list[str]
    sourcesFailed: list[str]
    jobsFound: int
    jobsNew: int
    jobsDuplicate: int
    errorSummary: str | None
    createdAt: datetime


class SearchRunListOut(BaseModel):
    items: list[SearchRunOut]
    total: int
    limit: int
    offset: int
