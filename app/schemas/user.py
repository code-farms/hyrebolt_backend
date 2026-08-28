# camelCase wire contract, mirrored by the frontend zod schemas.
import json
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.models import RemotePreference, SkillProficiency
from app.schemas.auth import UserOut

# One free-text list entry (role, location, company, industry).
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
# `education` is free-form JSON the UI edits as a block; cap what lands in jsonb.
MAX_EDUCATION_JSON_BYTES = 20_000


class SkillIn(BaseModel):
    skillName: str = Field(min_length=1, max_length=80)
    proficiency: SkillProficiency = SkillProficiency.INTERMEDIATE
    yearsOfExperience: float | None = Field(default=None, ge=0, le=60)


class SkillOut(BaseModel):
    skillName: str
    proficiency: SkillProficiency
    yearsOfExperience: float | None


class ProfileOut(BaseModel):
    phone: str | None
    currentRole: str | None
    yearsOfExperience: float | None
    targetRoles: list[str]
    preferredLocations: list[str]
    remotePreference: RemotePreference
    minimumSalary: int | None
    preferredSalary: int | None
    salaryCurrency: str
    noticePeriodDays: int | None
    education: Any | None
    industries: list[str]
    preferredCompanies: list[str]
    excludedCompanies: list[str]
    # Notification preferences (Phase 10)
    emailEnabled: bool
    telegramEnabled: bool
    telegramChatId: str | None
    dailyDigestEnabled: bool
    digestMinScore: int
    digestMaxJobs: int
    digestTime: str | None


class ProfileUpdate(BaseModel):
    """All fields optional: only provided keys are written (exclude_unset)."""

    phone: str | None = Field(default=None, max_length=32)
    currentRole: str | None = Field(default=None, max_length=120)
    yearsOfExperience: float | None = Field(default=None, ge=0, le=60)
    # Lists fan out into every scheduled search and every LLM prompt: bounded.
    targetRoles: list[ShortText] | None = Field(default=None, max_length=30)
    preferredLocations: list[ShortText] | None = Field(default=None, max_length=30)
    remotePreference: RemotePreference | None = None
    minimumSalary: int | None = Field(default=None, ge=0)
    preferredSalary: int | None = Field(default=None, ge=0)
    salaryCurrency: str | None = Field(default=None, min_length=3, max_length=3)
    noticePeriodDays: int | None = Field(default=None, ge=0, le=365)
    education: Any | None = None
    industries: list[ShortText] | None = Field(default=None, max_length=30)
    preferredCompanies: list[ShortText] | None = Field(default=None, max_length=50)
    excludedCompanies: list[ShortText] | None = Field(default=None, max_length=50)
    # Notification preferences (Phase 10)
    emailEnabled: bool | None = None
    telegramEnabled: bool | None = None
    telegramChatId: str | None = Field(default=None, max_length=64)
    dailyDigestEnabled: bool | None = None
    digestMinScore: int | None = Field(default=None, ge=0, le=100)
    digestMaxJobs: int | None = Field(default=None, ge=1, le=50)
    digestTime: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")

    @field_validator("education")
    @classmethod
    def bound_education(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, dict | list | str):
            raise TypeError("education must be an object, a list or a string")
        if len(json.dumps(value)) > MAX_EDUCATION_JSON_BYTES:
            raise ValueError(f"education must be under {MAX_EDUCATION_JSON_BYTES} bytes")
        return value


class SkillsUpdate(BaseModel):
    skills: list[SkillIn] = Field(max_length=100)


class MeResponse(BaseModel):
    user: UserOut
    profile: ProfileOut | None
    skills: list[SkillOut]
