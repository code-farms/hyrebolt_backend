# camelCase wire contract. All optional fields default to None/[]: absent data
# stays null through validation, storage, and the API — never invented.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import EmploymentType

WorkMode = Literal["REMOTE", "HYBRID", "ONSITE"]

# Bump whenever the job-analysis SYSTEM_PROMPT or prompt layout changes: stored
# analyses from older versions are treated as stale (re-analyzed by the daily
# agent, hidden from the API until then). Lives here, not in the service, so the
# wire serializers can compare against it without importing the service layer.
JOB_ANALYSIS_PROMPT_VERSION = "v1"


class SalaryOut(BaseModel):
    min: int | None = None
    max: int | None = None
    currency: str | None = None


class JobAnalysisResult(BaseModel):
    """The structured output contract for the LLM (Phase 7 spec shape)."""

    title: str | None = None
    seniority: str | None = None
    skillsRequired: list[str] = Field(default_factory=list)
    skillsPreferred: list[str] = Field(default_factory=list)
    experienceMin: float | None = Field(default=None, ge=0, le=60)
    experienceMax: float | None = Field(default=None, ge=0, le=60)
    location: str | None = None
    workMode: WorkMode | None = None
    employmentType: EmploymentType | None = None
    salary: SalaryOut | None = None
    responsibilities: list[str] = Field(default_factory=list)
    techStack: list[str] = Field(default_factory=list)
    industry: str | None = None
    confidence: float = Field(default=0.0)

    @field_validator("workMode", mode="before")
    @classmethod
    def unknown_work_mode_to_none(cls, value: object) -> str | None:
        """Values outside the enum mean 'unknown', never an error."""
        if not isinstance(value, str):
            return None
        upper = value.strip().upper().replace("-", "_").replace(" ", "_")
        return upper if upper in ("REMOTE", "HYBRID", "ONSITE") else None

    @field_validator("employmentType", mode="before")
    @classmethod
    def unknown_employment_type_to_none(cls, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        upper = value.strip().upper().replace("-", "_").replace(" ", "_")
        return upper if upper in EmploymentType.__members__ else None

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0


class JobAnalysisOut(BaseModel):
    jobId: str
    analysis: JobAnalysisResult
    confidence: float | None
    model: str
    promptVersion: str
    inputTokens: int | None
    outputTokens: int | None
    processedAt: datetime
