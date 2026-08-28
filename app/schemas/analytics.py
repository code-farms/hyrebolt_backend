# camelCase wire contract, mirrored by the frontend zod schemas.
"""Phase 17 analytics payloads. Aggregates only: counts, rates, source /
company / role labels. Never recruiter details, notes, descriptions or job
ids — nothing here is needed to identify a person or a posting.

Scoping: ``Job`` has no owner (single-user personal agent), so discovery
volumes ("discovered", "deduplicated", "analyzed", per-source "jobsFound")
are platform-wide. Everything derived from ``JobMatch`` / ``Application`` is
scoped to the requesting user. Rates are percentages rounded to one decimal
and are ``0.0`` when the denominator is zero.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AnalyticsRange = Literal[7, 30, 90]
ANALYTICS_RANGES: tuple[int, ...] = (7, 30, 90)


class DiscoveryMetricsOut(BaseModel):
    """jobsDiscovered = jobs created in the window; jobsDeduplicated =
    SUM(SearchRun.jobsDuplicate) over runs in the window (listings merged into
    an existing job); jobsAnalyzed / jobsMatched are counted over the jobs
    discovered in the window so the funnel is monotonic. "Matched" means the
    user's match score is >= relevantMinScore. analyzedRate = analyzed /
    discovered ·100; matchedRate = matched / discovered ·100."""

    jobsDiscovered: int
    jobsDeduplicated: int
    jobsAnalyzed: int
    jobsMatched: int
    analyzedRate: float
    matchedRate: float


class ApplicationFunnelOut(BaseModel):
    """Over the user's tracked applications created in the window (soft-deleted
    excluded). saved = every tracked application (each starts as SAVED);
    applied = appliedAt set; interviews / offers = ever reached that stage
    (ApplicationEvent history); rejected = current status. applyRate =
    applied / saved ·100; interviewRate = interviews / applied ·100;
    offerRate = offers / applied ·100."""

    saved: int
    applied: int
    interviews: int
    offers: int
    rejected: int
    applyRate: float
    interviewRate: float
    offerRate: float


class SourcePerformanceOut(BaseModel):
    """One row per job source. jobsFound is platform-wide (every listing of a
    job discovered in the window credits its source); relevantJobs / saved /
    applied / interviews are the user's. relevanceRate = relevant / found ·100;
    applyRate = applied / relevant ·100; interviewRate = interviews / applied ·100."""

    name: str
    displayName: str
    jobsFound: int
    relevantJobs: int
    saved: int
    applied: int
    interviews: int
    relevanceRate: float
    applyRate: float
    interviewRate: float


class RolePerformanceOut(BaseModel):
    """Titles folded into role families (see app.utils.role_family). Same
    scoping and rate definitions as SourcePerformanceOut."""

    family: str
    label: str
    jobsFound: int
    relevantJobs: int
    saved: int
    applied: int
    interviews: int
    relevanceRate: float
    applyRate: float


class CompanyPerformanceOut(BaseModel):
    """Top companies by the user's engagement (applied, interviews, relevant,
    found). companyId is null when entity resolution failed and jobs were
    grouped by their raw company name."""

    companyId: str | None
    companyName: str
    jobsFound: int
    relevantJobs: int
    saved: int
    applied: int
    interviews: int


class TimeSeriesPointOut(BaseModel):
    """One calendar day in the configured timezone (YYYY-MM-DD). Zero-filled."""

    date: str
    jobsDiscovered: int
    jobsMatched: int
    applied: int
    interviews: int


class AnalyticsOverviewOut(BaseModel):
    range: AnalyticsRange
    since: datetime
    until: datetime
    timezone: str
    relevantMinScore: float
    discovery: DiscoveryMetricsOut
    applications: ApplicationFunnelOut
    sources: list[SourcePerformanceOut]
    roles: list[RolePerformanceOut]
    companies: list[CompanyPerformanceOut]
    timeseries: list[TimeSeriesPointOut]
