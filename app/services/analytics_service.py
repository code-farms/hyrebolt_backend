"""Phase 17: job-search analytics.

The repository returns raw aggregates; this service owns the time window,
rate maths, role-family folding and zero-filled time series. Pure Python on
top of eight aggregation queries — no per-row work.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.core.exceptions import InvalidInputError
from app.core.logging import get_logger
from app.db.generated.models import User
from app.repositories import AnalyticsRepository
from app.schemas.analytics import (
    ANALYTICS_RANGES,
    AnalyticsOverviewOut,
    ApplicationFunnelOut,
    CompanyPerformanceOut,
    DiscoveryMetricsOut,
    RolePerformanceOut,
    SourcePerformanceOut,
    TimeSeriesPointOut,
)
from app.utils.role_family import classify_role, role_family_label

logger = get_logger(__name__)


@dataclass(frozen=True)
class AnalyticsWindow:
    """Calendar window in the user's configured timezone: ``range_days`` local
    days ending today, ``since_utc`` being the first day's local midnight."""

    range_days: int
    tz_name: str
    since_local: date
    until_local: date
    since_utc: datetime
    now_utc: datetime

    def days(self) -> list[date]:
        return [self.since_local + timedelta(days=offset) for offset in range(self.range_days)]


def resolve_timezone(name: str) -> tuple[ZoneInfo, str]:
    """Settings.timezone, falling back to UTC when the name is not a valid
    IANA zone (Postgres would otherwise reject ``AT TIME ZONE``)."""
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC"), "UTC"


def build_window(range_days: int, tz_name: str, now: datetime | None = None) -> AnalyticsWindow:
    zone, resolved = resolve_timezone(tz_name)
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    until_local = now_utc.astimezone(zone).date()
    since_local = until_local - timedelta(days=range_days - 1)
    since_utc = datetime.combine(since_local, time.min, tzinfo=zone).astimezone(UTC)
    return AnalyticsWindow(
        range_days=range_days,
        tz_name=resolved,
        since_local=since_local,
        until_local=until_local,
        since_utc=since_utc,
        now_utc=now_utc,
    )


def rate(numerator: int, denominator: int) -> float:
    """Percentage rounded to one decimal, 0.0 when there is no denominator —
    the same convention as ApplicationService.stats."""
    return round(numerator / denominator * 100, 1) if denominator else 0.0


class AnalyticsService:
    def __init__(self, analytics: AnalyticsRepository, *, settings: Settings) -> None:
        self._analytics = analytics
        self._settings = settings

    async def overview(
        self, user: User, range_days: int, *, now: datetime | None = None
    ) -> AnalyticsOverviewOut:
        if range_days not in ANALYTICS_RANGES:
            allowed = ", ".join(str(days) for days in ANALYTICS_RANGES)
            raise InvalidInputError(f"range must be one of {allowed}")
        window = build_window(range_days, self._settings.timezone, now)
        threshold = self._settings.analytics_relevant_min_score
        repo, uid, since = self._analytics, user.id, window.since_utc

        discovery = await repo.discovery_counts(uid, since, threshold)
        deduplicated = await repo.deduplicated_count(since)
        funnel = await repo.application_funnel(uid, since)
        sources = await repo.source_performance(uid, since, threshold)
        titles = await repo.title_performance(uid, since, threshold)
        companies = await repo.company_performance(
            uid, since, threshold, self._settings.analytics_company_limit
        )
        daily_jobs = await repo.daily_jobs(uid, since, window.tz_name, threshold)
        daily_events = await repo.daily_application_events(uid, since, window.tz_name)

        result = AnalyticsOverviewOut(
            range=range_days,  # type: ignore[arg-type]  # validated against ANALYTICS_RANGES above
            since=window.since_utc,
            until=window.now_utc,
            timezone=window.tz_name,
            relevantMinScore=threshold,
            discovery=_discovery_out(discovery, deduplicated),
            applications=_funnel_out(funnel),
            sources=[_source_out(row) for row in sources],
            roles=_fold_roles(titles),
            companies=[_company_out(row) for row in companies],
            timeseries=_zero_fill(window.days(), daily_jobs, daily_events),
        )
        logger.info(
            "analytics_overview_built",
            user_id=user.id,
            range=range_days,
            jobs_discovered=result.discovery.jobsDiscovered,
            applications=result.applications.saved,
        )
        return result


def _discovery_out(counts: dict[str, int], deduplicated: int) -> DiscoveryMetricsOut:
    discovered = counts.get("discovered", 0)
    analyzed = counts.get("analyzed", 0)
    matched = counts.get("matched", 0)
    return DiscoveryMetricsOut(
        jobsDiscovered=discovered,
        jobsDeduplicated=deduplicated,
        jobsAnalyzed=analyzed,
        jobsMatched=matched,
        analyzedRate=rate(analyzed, discovered),
        matchedRate=rate(matched, discovered),
    )


def _funnel_out(counts: dict[str, int]) -> ApplicationFunnelOut:
    saved = counts.get("saved", 0)
    applied = counts.get("applied", 0)
    interviews = counts.get("interviews", 0)
    offers = counts.get("offers", 0)
    return ApplicationFunnelOut(
        saved=saved,
        applied=applied,
        interviews=interviews,
        offers=offers,
        rejected=counts.get("rejected", 0),
        applyRate=rate(applied, saved),
        interviewRate=rate(interviews, applied),
        offerRate=rate(offers, applied),
    )


def _source_out(row: dict[str, Any]) -> SourcePerformanceOut:
    return SourcePerformanceOut(
        name=row["name"],
        displayName=row["displayName"],
        jobsFound=row["jobsFound"],
        relevantJobs=row["relevant"],
        saved=row["saved"],
        applied=row["applied"],
        interviews=row["interviews"],
        relevanceRate=rate(row["relevant"], row["jobsFound"]),
        applyRate=rate(row["applied"], row["relevant"]),
        interviewRate=rate(row["interviews"], row["applied"]),
    )


def _company_out(row: dict[str, Any]) -> CompanyPerformanceOut:
    return CompanyPerformanceOut(
        companyId=row.get("companyId"),
        companyName=row["companyName"],
        jobsFound=row["jobsFound"],
        relevantJobs=row["relevant"],
        saved=row["saved"],
        applied=row["applied"],
        interviews=row["interviews"],
    )


_ENGAGEMENT_KEYS = ("jobsFound", "relevant", "saved", "applied", "interviews")


def _fold_roles(title_rows: list[dict[str, Any]]) -> list[RolePerformanceOut]:
    """Sum per-title aggregates into role families; busiest family first."""
    totals: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(_ENGAGEMENT_KEYS, 0))
    for row in title_rows:
        bucket = totals[classify_role(row.get("title") or "")]
        for key in _ENGAGEMENT_KEYS:
            bucket[key] += int(row.get(key) or 0)
    roles = [
        RolePerformanceOut(
            family=family,
            label=role_family_label(family),
            jobsFound=counts["jobsFound"],
            relevantJobs=counts["relevant"],
            saved=counts["saved"],
            applied=counts["applied"],
            interviews=counts["interviews"],
            relevanceRate=rate(counts["relevant"], counts["jobsFound"]),
            applyRate=rate(counts["applied"], counts["relevant"]),
        )
        for family, counts in totals.items()
        if counts["jobsFound"] > 0
    ]
    roles.sort(key=lambda role: (-role.jobsFound, -role.relevantJobs, role.label))
    return roles


def _zero_fill(
    days: list[date], job_rows: list[dict[str, Any]], event_rows: list[dict[str, Any]]
) -> list[TimeSeriesPointOut]:
    jobs_by_day = {row["day"]: row for row in job_rows}
    events_by_day = {row["day"]: row for row in event_rows}
    points: list[TimeSeriesPointOut] = []
    for day in days:
        key = day.isoformat()
        jobs = jobs_by_day.get(key, {})
        events = events_by_day.get(key, {})
        points.append(
            TimeSeriesPointOut(
                date=key,
                jobsDiscovered=int(jobs.get("discovered") or 0),
                jobsMatched=int(jobs.get("matched") or 0),
                applied=int(events.get("applied") or 0),
                interviews=int(events.get("interviews") or 0),
            )
        )
    return points
