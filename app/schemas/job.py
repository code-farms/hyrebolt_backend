# camelCase wire contract, mirrored by the frontend zod schemas (Phase 11).
from datetime import datetime

from pydantic import BaseModel

from app.db.generated.models import Job, JobAnalysis
from app.models import EmploymentType, MatchFeedback, MatchRecommendation
from app.schemas.analysis import JobAnalysisOut, JobAnalysisResult


class JobMatchSummaryOut(BaseModel):
    """Slim viewer-match context for job cards; the full component breakdown
    lives on GET /jobs/{id}/match."""

    overallScore: float
    recommendation: MatchRecommendation | None
    feedback: MatchFeedback | None


class JobSourceListingOut(BaseModel):
    sourceName: str
    displayName: str
    url: str | None
    externalId: str | None
    isPrimary: bool


class JobOut(BaseModel):
    id: str
    title: str
    companyName: str
    location: str | None
    country: str | None
    remote: bool
    hybrid: bool
    employmentType: EmploymentType | None
    experienceMin: float | None
    experienceMax: float | None
    salaryMin: int | None
    salaryMax: int | None
    salaryCurrency: str | None
    description: str | None
    sourceUrl: str | None
    canonicalUrl: str | None
    postedAt: datetime | None
    discoveredAt: datetime
    # Phase 6 source relationships: every listing this job was seen on, and
    # near-duplicates linked below the merge-confidence threshold.
    sources: list[JobSourceListingOut]
    duplicateOfId: str | None
    duplicateIds: list[str]
    # AI analysis (Phase 7), present once the job has been analyzed.
    analysis: JobAnalysisOut | None
    # Viewer context (Phase 11): the caller's match summary + saved flag.
    match: JobMatchSummaryOut | None = None
    saved: bool = False
    createdAt: datetime


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


def job_out(job: Job) -> JobOut:
    listings = job.listings or []
    duplicates = job.duplicates or []
    viewer_matches = getattr(job, "matches", None) or []
    viewer_saved = getattr(job, "savedBy", None) or []
    match_summary = (
        JobMatchSummaryOut(
            overallScore=viewer_matches[0].overallScore,
            recommendation=viewer_matches[0].recommendation,
            feedback=viewer_matches[0].feedback,
        )
        if viewer_matches
        else None
    )
    return JobOut(
        id=job.id,
        title=job.title,
        companyName=job.companyName,
        location=job.location,
        country=job.country,
        remote=job.remote,
        hybrid=job.hybrid,
        employmentType=job.employmentType,
        experienceMin=job.experienceMin,
        experienceMax=job.experienceMax,
        salaryMin=job.salaryMin,
        salaryMax=job.salaryMax,
        salaryCurrency=job.salaryCurrency,
        description=job.description,
        sourceUrl=job.sourceUrl,
        canonicalUrl=job.canonicalUrl,
        postedAt=job.postedAt,
        discoveredAt=job.discoveredAt,
        sources=[
            JobSourceListingOut(
                sourceName=listing.source.name if listing.source else "",
                displayName=listing.source.displayName if listing.source else "",
                url=listing.sourceUrl or listing.canonicalUrl,
                externalId=listing.externalId,
                isPrimary=listing.isPrimary,
            )
            for listing in listings
        ],
        duplicateOfId=job.duplicateOfId,
        duplicateIds=[duplicate.id for duplicate in duplicates],
        analysis=analysis_out(job.analysis) if getattr(job, "analysis", None) else None,
        match=match_summary,
        saved=bool(viewer_saved),
        createdAt=job.createdAt,
    )


def analysis_out(row: JobAnalysis) -> JobAnalysisOut:
    return JobAnalysisOut(
        jobId=row.jobId,
        analysis=JobAnalysisResult.model_validate(row.analysis),
        confidence=row.confidence,
        model=row.model,
        promptVersion=row.promptVersion,
        inputTokens=row.inputTokens,
        outputTokens=row.outputTokens,
        processedAt=row.processedAt,
    )
