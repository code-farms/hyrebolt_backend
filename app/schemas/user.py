# camelCase wire contract, mirrored by the frontend zod schemas.
from typing import Any

from pydantic import BaseModel, Field

from app.models import RemotePreference, SkillProficiency
from app.schemas.auth import UserOut


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
    targetRoles: list[str] | None = None
    preferredLocations: list[str] | None = None
    remotePreference: RemotePreference | None = None
    minimumSalary: int | None = Field(default=None, ge=0)
    preferredSalary: int | None = Field(default=None, ge=0)
    salaryCurrency: str | None = Field(default=None, min_length=3, max_length=3)
    noticePeriodDays: int | None = Field(default=None, ge=0, le=365)
    education: Any | None = None
    industries: list[str] | None = None
    preferredCompanies: list[str] | None = None
    excludedCompanies: list[str] | None = None
    # Notification preferences (Phase 10)
    emailEnabled: bool | None = None
    telegramEnabled: bool | None = None
    telegramChatId: str | None = Field(default=None, max_length=64)
    dailyDigestEnabled: bool | None = None
    digestMinScore: int | None = Field(default=None, ge=0, le=100)
    digestMaxJobs: int | None = Field(default=None, ge=1, le=50)
    digestTime: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class SkillsUpdate(BaseModel):
    skills: list[SkillIn] = Field(max_length=100)


class MeResponse(BaseModel):
    user: UserOut
    profile: ProfileOut | None
    skills: list[SkillOut]
