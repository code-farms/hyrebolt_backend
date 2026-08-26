"""Fakes for the Phase 16 personalisation tests."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.models import MatchFeedback, PreferenceSignalKind
from app.services.preference_signal_service import PreferenceSignalService
from app.utils.normalization import normalize_company, normalize_location, normalize_title


@dataclass
class FakeSignalRow:
    id: str
    userId: str
    jobId: str | None
    kind: PreferenceSignalKind
    weight: float
    roleKey: str
    roleLabel: str
    companyId: str | None
    companyKey: str
    companyLabel: str
    locationKey: str | None
    workMode: str | None
    skills: list[str] = field(default_factory=list)
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeSignalRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str | None, str], FakeSignalRow] = {}

    async def list_for_user(self, user_id: str) -> list[FakeSignalRow]:
        return sorted(
            (r for r in self.rows.values() if r.userId == user_id), key=lambda r: r.createdAt
        )

    async def upsert(self, user_id: str, job_id: str, kind, data: dict[str, Any]) -> FakeSignalRow:
        key = (user_id, job_id, str(kind))
        existing = self.rows.get(key)
        row = FakeSignalRow(
            id=existing.id if existing else uuid.uuid4().hex,
            userId=user_id,
            jobId=job_id,
            kind=kind,
            weight=data["weight"],
            roleKey=data["roleKey"],
            roleLabel=data["roleLabel"],
            companyId=data["companyId"],
            companyKey=data["companyKey"],
            companyLabel=data["companyLabel"],
            locationKey=data["locationKey"],
            workMode=data["workMode"],
            skills=list(data["skills"]),
        )
        self.rows[key] = row
        return row

    async def delete_kinds(self, user_id: str, job_id: str, kinds) -> int:
        targets = [(user_id, job_id, str(k)) for k in kinds]
        before = len(self.rows)
        for target in targets:
            self.rows.pop(target, None)
        return before - len(self.rows)

    async def delete_by_id(self, user_id: str, signal_id: str) -> int:
        for key, row in list(self.rows.items()):
            if row.id == signal_id and row.userId == user_id:
                del self.rows[key]
                return 1
        return 0

    async def delete_all(self, user_id: str) -> int:
        keys = [k for k, r in self.rows.items() if r.userId == user_id]
        for key in keys:
            del self.rows[key]
        return len(keys)


class FakeAnalyses:
    def __init__(self, by_job: dict[str, dict[str, Any]] | None = None) -> None:
        self.by_job = by_job or {}

    async def get_by_job_id(self, job_id: str):
        data = self.by_job.get(job_id)
        return SimpleNamespace(analysis=data) if data else None


def make_job(
    *,
    job_id: str | None = None,
    title: str = "Backend Engineer",
    company: str = "Acme",
    company_id: str | None = "c-acme",
    location: str | None = "Bengaluru, India",
    remote: bool = False,
    hybrid: bool = False,
    analysis: dict[str, Any] | None = None,
    posted_days_ago: float | None = None,
    discovered_days_ago: float = 1.0,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=job_id or uuid.uuid4().hex,
        title=title,
        normalizedTitle=normalize_title(title),
        companyName=company,
        companyId=company_id,
        location=location,
        normalizedLocation=normalize_location(location),
        remote=remote,
        hybrid=hybrid,
        description="",
        deletedAt=None,
        postedAt=(now - timedelta(days=posted_days_ago)) if posted_days_ago is not None else None,
        discoveredAt=now - timedelta(days=discovered_days_ago),
        createdAt=now,
        analysis=SimpleNamespace(analysis=analysis) if analysis else None,
        listings=[],
        duplicates=[],
        savedBy=[],
        # jobs_api-compatible extras for job_out()
        country=None,
        employmentType=None,
        experienceMin=None,
        experienceMax=None,
        salaryMin=None,
        salaryMax=None,
        salaryCurrency=None,
        sourceUrl=None,
        canonicalUrl=None,
        duplicateOfId=None,
    )


def make_match(
    job: SimpleNamespace,
    *,
    user_id: str = "u1",
    score: float = 75.0,
    feedback: MatchFeedback | None = None,
    company_score: float | None = 50.0,
    watchlist_score: float | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=f"m-{job.id}",
        userId=user_id,
        jobId=job.id,
        overallScore=score,
        roleScore=None,
        skillScore=None,
        experienceScore=None,
        locationScore=None,
        salaryScore=None,
        workModeScore=None,
        industryScore=None,
        companyScore=company_score,
        watchlistScore=watchlist_score,
        recommendation=None,
        whyMatch=None,
        missingSkills=[],
        strengths=[],
        concerns=[],
        scoringVersion="rules-v2",
        aiModel=None,
        promptVersion=None,
        feedback=feedback,
        feedbackAt=None,
        job=job,
        createdAt=now,
        updatedAt=now,
    )


class FakeCandidateMatches:
    """Implements the JobMatchRepository surface RankingService uses."""

    def __init__(self, rows: list[SimpleNamespace], *, applied_job_ids: set[str] | None = None) -> None:
        self.rows = rows
        self.applied_job_ids = applied_job_ids or set()
        self.calls: list[dict[str, Any]] = []

    async def list_candidates_for_user(self, user_id: str, *, min_score: float, limit: int):
        self.calls.append({"min_score": min_score, "limit": limit})
        rows = [
            r
            for r in self.rows
            if r.userId == user_id
            and r.overallScore >= min_score
            and r.feedback != MatchFeedback.NOT_RELEVANT
            and r.jobId not in self.applied_job_ids
        ]
        rows.sort(key=lambda r: r.overallScore, reverse=True)
        return rows[:limit]

    async def list_ranked_for_user(self, user_id: str, *, limit: int, offset: int, min_score: float):
        rows = await self.list_candidates_for_user(user_id, min_score=min_score, limit=10_000)
        return rows[offset : offset + limit], len(rows)


class FakeJobsByScore:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    async def list_by_score(self, user_id: str, filters, *, min_score: float, limit: int, offset: int):
        rows = [r for r in self.rows if r.userId == user_id and r.overallScore >= min_score]
        rows.sort(key=lambda r: r.overallScore, reverse=True)
        return rows[offset : offset + limit], len(rows)


def make_signal_service(analyses: dict[str, dict[str, Any]] | None = None):
    repo = FakeSignalRepository()
    return PreferenceSignalService(repo, FakeAnalyses(analyses)), repo  # type: ignore[arg-type]


def company_key(name: str) -> str:
    return normalize_company(name)
