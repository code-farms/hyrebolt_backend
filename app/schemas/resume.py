# camelCase wire contract, mirrored by the frontend zod schemas (Phase 14).
#
# LLM-produced models are lenient: absent facts stay None/[] through
# validation, storage and the API — never invented. Lengths are capped because
# the resume text that feeds the prompt is untrusted input.
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.db.generated.models import Resume, ResumeAnalysis, ResumeVersion

MAX_ITEMS = 100
MAX_TEXT = 2000


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:MAX_TEXT] if text else None


def _clean_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value[:MAX_ITEMS]


def _clean_str_list(value: object) -> list[str]:
    return [item for item in (_clean_str(v) for v in _clean_list(value)) if item]


def _objects_only(value: object) -> list[Any]:
    """Keeps dicts (raw LLM output) and model instances (re-validation after
    grounding); drops strings/numbers the model put where objects belong."""
    return [item for item in _clean_list(value) if isinstance(item, dict | BaseModel)]


class _LenientModel(BaseModel):
    """Every str field is trimmed/capped; every list field is capped."""

    @field_validator("*", mode="before")
    @classmethod
    def _lenient(cls, value: object, info: Any) -> object:
        annotation = cls.model_fields[info.field_name].annotation
        if annotation is str or annotation == (str | None):
            return _clean_str(value)
        if annotation == list[str]:
            return _clean_str_list(value)
        if getattr(annotation, "__origin__", None) is list:
            return _clean_list(value)
        return value


# ── resume extraction ────────────────────────────────────────────────────────


class ExperienceItem(_LenientModel):
    title: str | None = None
    company: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)


class ProjectItem(_LenientModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)


class EducationItem(_LenientModel):
    degree: str | None = None
    institution: str | None = None
    year: str | None = None


class ResumeAnalysisResult(_LenientModel):
    summary: str | None = None
    totalYearsExperience: float | None = None
    experience: list[ExperienceItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @field_validator("totalYearsExperience", mode="before")
    @classmethod
    def clamp_years(cls, value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return max(0.0, min(60.0, float(value)))

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return 0.0
        return max(0.0, min(1.0, float(value)))

    @field_validator("experience", "projects", "education", mode="before")
    @classmethod
    def drop_non_objects(cls, value: object) -> list[Any]:
        return _objects_only(value)


# ── gap analysis ─────────────────────────────────────────────────────────────


class GapExperience(_LenientModel):
    title: str | None = None
    company: str | None = None
    why: str | None = None


class GapWeakArea(_LenientModel):
    area: str | None = None
    why: str | None = None


class GapSuggestion(_LenientModel):
    suggestion: str | None = None
    why: str | None = None
    basedOn: str | None = None  # verbatim quote from the resume/profile it relies on


class GapAIResult(_LenientModel):
    """The LLM-produced portion of a gap analysis (what gets cached)."""

    relevantExperience: list[GapExperience] = Field(default_factory=list)
    weakAreas: list[GapWeakArea] = Field(default_factory=list)
    suggestedImprovements: list[GapSuggestion] = Field(default_factory=list)

    @field_validator("relevantExperience", "weakAreas", "suggestedImprovements", mode="before")
    @classmethod
    def drop_non_objects(cls, value: object) -> list[Any]:
        return _objects_only(value)


class ResumeGapResult(BaseModel):
    matchedSkills: list[str]
    missingSkills: list[str]
    relevantExperience: list[GapExperience]
    weakAreas: list[GapWeakArea]
    suggestedImprovements: list[GapSuggestion]
    aiAvailable: bool


# ── wire models ──────────────────────────────────────────────────────────────


class ResumeAnalysisOut(BaseModel):
    analysis: ResumeAnalysisResult
    confidence: float | None
    model: str | None
    promptVersion: str | None
    processedAt: datetime


class ResumeVersionOut(BaseModel):
    id: str
    resumeId: str
    versionNumber: int
    fileName: str
    mimeType: str
    fileSize: int
    createdAt: datetime
    analysis: ResumeAnalysisOut | None


class ResumeVersionDetailOut(ResumeVersionOut):
    extractedText: str


class ResumeOut(BaseModel):
    id: str
    title: str
    isSelected: bool
    latestVersionId: str | None
    versions: list[ResumeVersionOut]  # newest first
    createdAt: datetime
    updatedAt: datetime


class ResumeListOut(BaseModel):
    items: list[ResumeOut]
    total: int
    selectedResumeId: str | None


class ResumeGapOut(BaseModel):
    resumeId: str
    versionId: str
    jobId: str
    result: ResumeGapResult
    model: str | None
    promptVersion: str
    processedAt: datetime


def analysis_out(row: ResumeAnalysis) -> ResumeAnalysisOut:
    return ResumeAnalysisOut(
        analysis=ResumeAnalysisResult.model_validate(row.analysis),
        confidence=row.confidence,
        model=row.model,
        promptVersion=row.promptVersion,
        processedAt=row.processedAt,
    )


def version_out(version: ResumeVersion) -> ResumeVersionOut:
    analysis = getattr(version, "analysis", None)
    return ResumeVersionOut(
        id=version.id,
        resumeId=version.resumeId,
        versionNumber=version.versionNumber,
        fileName=version.fileName,
        mimeType=version.mimeType,
        fileSize=version.fileSize,
        createdAt=version.createdAt,
        analysis=analysis_out(analysis) if analysis is not None else None,
    )


def version_detail_out(version: ResumeVersion) -> ResumeVersionDetailOut:
    base = version_out(version)
    return ResumeVersionDetailOut(**base.model_dump(), extractedText=version.extractedText)


def resume_out(resume: Resume, *, selected_resume_id: str | None) -> ResumeOut:
    versions = sorted(resume.versions or [], key=lambda v: v.versionNumber, reverse=True)
    return ResumeOut(
        id=resume.id,
        title=resume.title,
        isSelected=resume.id == selected_resume_id,
        latestVersionId=versions[0].id if versions else None,
        versions=[version_out(v) for v in versions],
        createdAt=resume.createdAt,
        updatedAt=resume.updatedAt,
    )
