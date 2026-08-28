"""Phase 17 analytics aggregates.

Everything here is one aggregation query per panel, executed in Postgres via
parameterised raw SQL (``$n`` placeholders, never string formatting). Prisma's
``group_by`` cannot traverse relations or truncate dates, which every panel
below needs. Rows come back as plain dicts; ``bigint`` counts are deserialised
to ``int``, dates are cast to text in SQL because the raw-query layer leaves
timestamps as strings.

Scoping: ``Job`` has no owner, so job volumes are platform-wide; anything
joined through ``JobMatch`` / ``Application`` is filtered by ``userId``.
All timestamps are stored as naive UTC (``TIMESTAMP(3)``).
"""

from datetime import UTC, datetime
from typing import Any

from app.repositories.base import BaseRepository

# ── shared fragments ─────────────────────────────────────────────────────────

_INTERVIEW_EXISTS = (
    'EXISTS (SELECT 1 FROM "ApplicationEvent" e '
    "WHERE e.\"applicationId\" = a.id AND e.status = 'INTERVIEW')"
)
_OFFER_EXISTS = (
    'EXISTS (SELECT 1 FROM "ApplicationEvent" e '
    "WHERE e.\"applicationId\" = a.id AND e.status = 'OFFER')"
)

# $1 = userId, $3 = relevance threshold. Joins land on the (userId, jobId)
# unique indexes, so they never fan out a job row.
_USER_JOINS = (
    'LEFT JOIN "JobMatch" m ON m."jobId" = j.id AND m."userId" = $1 '
    'LEFT JOIN "Application" a ON a."jobId" = j.id AND a."userId" = $1 '
    'AND a."deletedAt" IS NULL '
)
_ENGAGEMENT_COLUMNS = (
    'COUNT(DISTINCT j.id) AS "jobsFound", '
    'COUNT(DISTINCT j.id) FILTER (WHERE m."overallScore" >= $3::float8) AS relevant, '
    "COUNT(DISTINCT j.id) FILTER (WHERE a.id IS NOT NULL) AS saved, "
    'COUNT(DISTINCT j.id) FILTER (WHERE a."appliedAt" IS NOT NULL) AS applied, '
    "COUNT(DISTINCT j.id) FILTER (WHERE a.id IS NOT NULL AND " + _INTERVIEW_EXISTS + ") "
    "AS interviews "
)
_JOB_WINDOW = 'j."deletedAt" IS NULL AND j."createdAt" >= $2::timestamp '

# ── queries ──────────────────────────────────────────────────────────────────

_DISCOVERY_SQL = (
    "SELECT COUNT(*) AS discovered, "
    "COUNT(an.id) AS analyzed, "
    'COUNT(*) FILTER (WHERE m."overallScore" >= $3::float8) AS matched '
    'FROM "Job" j '
    'LEFT JOIN "JobAnalysis" an ON an."jobId" = j.id '
    'LEFT JOIN "JobMatch" m ON m."jobId" = j.id AND m."userId" = $1 '
    "WHERE " + _JOB_WINDOW
)

_DEDUPLICATED_SQL = (
    'SELECT COALESCE(SUM("jobsDuplicate"), 0)::bigint AS deduplicated '
    'FROM "SearchRun" WHERE "createdAt" >= $1::timestamp'
)

_FUNNEL_SQL = (
    "SELECT COUNT(*) AS saved, "
    'COUNT(*) FILTER (WHERE a."appliedAt" IS NOT NULL) AS applied, '
    "COUNT(*) FILTER (WHERE " + _INTERVIEW_EXISTS + ") AS interviews, "
    "COUNT(*) FILTER (WHERE " + _OFFER_EXISTS + ") AS offers, "
    "COUNT(*) FILTER (WHERE a.status = 'REJECTED') AS rejected "
    'FROM "Application" a '
    'WHERE a."userId" = $1 AND a."deletedAt" IS NULL AND a."createdAt" >= $2::timestamp'
)

# Every source is listed (LEFT JOIN), so sources that found nothing show zeros.
_SOURCE_SQL = (
    'SELECT s.name, s."displayName", ' + _ENGAGEMENT_COLUMNS + 'FROM "JobSource" s '
    'LEFT JOIN "JobSourceListing" l ON l."sourceId" = s.id '
    'LEFT JOIN "Job" j ON j.id = l."jobId" AND ' + _JOB_WINDOW + _USER_JOINS + 'GROUP BY s.id, s.name, s."displayName" '
    'ORDER BY "jobsFound" DESC, s."displayName" ASC'
)

_TITLE_SQL = (
    'SELECT j."normalizedTitle" AS title, ' + _ENGAGEMENT_COLUMNS + 'FROM "Job" j ' + _USER_JOINS + "WHERE " + _JOB_WINDOW + 'GROUP BY j."normalizedTitle"'
)

_COMPANY_SQL = (
    'SELECT j."companyId", MIN(j."companyName") AS "companyName", '
    + _ENGAGEMENT_COLUMNS
    + 'FROM "Job" j '
    + _USER_JOINS
    + "WHERE "
    + _JOB_WINDOW
    + 'GROUP BY COALESCE(j."companyId", lower(j."companyName")), j."companyId" '
    'HAVING COUNT(*) FILTER (WHERE m."overallScore" >= $3::float8 OR a.id IS NOT NULL) > 0 '
    'ORDER BY applied DESC, interviews DESC, relevant DESC, "jobsFound" DESC, '
    '"companyName" ASC '
    "LIMIT $4::int"
)

_DAILY_JOBS_SQL = (
    "SELECT (j.\"createdAt\" AT TIME ZONE 'UTC' AT TIME ZONE $4::text)::date::text AS day, "
    "COUNT(*) AS discovered, "
    'COUNT(*) FILTER (WHERE m."overallScore" >= $3::float8) AS matched '
    'FROM "Job" j '
    'LEFT JOIN "JobMatch" m ON m."jobId" = j.id AND m."userId" = $1 '
    "WHERE " + _JOB_WINDOW + "GROUP BY 1 ORDER BY 1"
)

_DAILY_EVENTS_SQL = (
    "SELECT (e.\"occurredAt\" AT TIME ZONE 'UTC' AT TIME ZONE $3::text)::date::text AS day, "
    "COUNT(DISTINCT e.\"applicationId\") FILTER (WHERE e.status = 'APPLIED') AS applied, "
    "COUNT(DISTINCT e.\"applicationId\") FILTER (WHERE e.status = 'INTERVIEW') AS interviews "
    'FROM "ApplicationEvent" e '
    'JOIN "Application" a ON a.id = e."applicationId" AND a."userId" = $1 '
    'AND a."deletedAt" IS NULL '
    'WHERE e."occurredAt" >= $2::timestamp AND e.status IN (\'APPLIED\', \'INTERVIEW\') '
    "GROUP BY 1 ORDER BY 1"
)


def _utc_param(moment: datetime) -> str:
    """Naive-UTC literal for a ``$n::timestamp`` placeholder."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    return int(value) if value is not None else 0


class AnalyticsRepository(BaseRepository):
    async def discovery_counts(
        self, user_id: str, since: datetime, threshold: float
    ) -> dict[str, int]:
        rows = await self._prisma.query_raw(_DISCOVERY_SQL, user_id, _utc_param(since), threshold)
        row = rows[0] if rows else {}
        return {key: _int(row, key) for key in ("discovered", "analyzed", "matched")}

    async def deduplicated_count(self, since: datetime) -> int:
        rows = await self._prisma.query_raw(_DEDUPLICATED_SQL, _utc_param(since))
        return _int(rows[0], "deduplicated") if rows else 0

    async def application_funnel(self, user_id: str, since: datetime) -> dict[str, int]:
        rows = await self._prisma.query_raw(_FUNNEL_SQL, user_id, _utc_param(since))
        row = rows[0] if rows else {}
        keys = ("saved", "applied", "interviews", "offers", "rejected")
        return {key: _int(row, key) for key in keys}

    async def source_performance(
        self, user_id: str, since: datetime, threshold: float
    ) -> list[dict[str, Any]]:
        rows = await self._prisma.query_raw(_SOURCE_SQL, user_id, _utc_param(since), threshold)
        return [
            {"name": row["name"], "displayName": row["displayName"], **_engagement(row)}
            for row in rows
        ]

    async def title_performance(
        self, user_id: str, since: datetime, threshold: float
    ) -> list[dict[str, Any]]:
        rows = await self._prisma.query_raw(_TITLE_SQL, user_id, _utc_param(since), threshold)
        return [{"title": row.get("title") or "", **_engagement(row)} for row in rows]

    async def company_performance(
        self, user_id: str, since: datetime, threshold: float, limit: int
    ) -> list[dict[str, Any]]:
        rows = await self._prisma.query_raw(
            _COMPANY_SQL, user_id, _utc_param(since), threshold, limit
        )
        return [
            {
                "companyId": row.get("companyId"),
                "companyName": row.get("companyName") or "",
                **_engagement(row),
            }
            for row in rows
        ]

    async def daily_jobs(
        self, user_id: str, since: datetime, tz_name: str, threshold: float
    ) -> list[dict[str, Any]]:
        rows = await self._prisma.query_raw(
            _DAILY_JOBS_SQL, user_id, _utc_param(since), threshold, tz_name
        )
        return [
            {"day": row["day"], "discovered": _int(row, "discovered"), "matched": _int(row, "matched")}
            for row in rows
        ]

    async def daily_application_events(
        self, user_id: str, since: datetime, tz_name: str
    ) -> list[dict[str, Any]]:
        rows = await self._prisma.query_raw(_DAILY_EVENTS_SQL, user_id, _utc_param(since), tz_name)
        return [
            {"day": row["day"], "applied": _int(row, "applied"), "interviews": _int(row, "interviews")}
            for row in rows
        ]


def _engagement(row: dict[str, Any]) -> dict[str, int]:
    return {
        "jobsFound": _int(row, "jobsFound"),
        "relevant": _int(row, "relevant"),
        "saved": _int(row, "saved"),
        "applied": _int(row, "applied"),
        "interviews": _int(row, "interviews"),
    }
