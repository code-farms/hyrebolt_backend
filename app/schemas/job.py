# camelCase wire contract, mirrored by the frontend zod schemas (Phase 11).
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.generated.models import Job, JobAnalysis


class RankingOut(BaseModel):
    """Phase 16: the personalised score and where every point came from.
    finalScore = baseScore + preference + freshness + company + feedback (clamped 0-100)."""

    finalScore: float
    baseScore: float
    preferenceScore: float
    freshnessScore: float
    companyScore: float
    feedbackScore: float
    explanations: list[str] = Field(default_factory=list)


from app.models import EmploymentType, MatchFeedback, MatchRecommendation
from app.schemas.analysis import (
    JOB_ANALYSIS_PROMPT_VERSION,
    JobAnalysisOut,
    JobAnalysisResult,
)


class JobMatchSummaryOut(BaseModel):
    """Slim viewer-match context for job cards; the full component breakdown
    lives on GET /jobs/{id}/match."""

    overallScore: float
    recommendation: MatchRecommendation | None
    feedback: MatchFeedback | None
    # Phase 13 "Watchlist Match": null unless the company is watchlisted.
    watchlistScore: float | None = None


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
    companyId: str | None = None  # Phase 13: link to /companies/{id} when resolved
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
    # Phase 16: set on personalised lists (recommended, sort=score).
    ranking: RankingOut | None = None
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
            watchlistScore=getattr(viewer_matches[0], "watchlistScore", None),
        )
        if viewer_matches
        else None
    )
    return JobOut(
        id=job.id,
        title=job.title,
        companyName=job.companyName,
        companyId=getattr(job, "companyId", None),
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
        analysis=_current_analysis_out(getattr(job, "analysis", None)),
        match=match_summary,
        saved=bool(viewer_saved),
        createdAt=job.createdAt,
    )


def _current_analysis_out(row: JobAnalysis | None) -> JobAnalysisOut | None:
    """A stale-version analysis (older prompt, or the mock provider's empty
    shape from before a real key was configured) is hidden so the client can
    request a fresh one instead of rendering an empty card."""
    if row is None or row.promptVersion != JOB_ANALYSIS_PROMPT_VERSION:
        return None
    return analysis_out(row)


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
