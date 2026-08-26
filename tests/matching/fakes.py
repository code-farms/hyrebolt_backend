import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.models import MatchFeedback, RemotePreference
from app.utils.normalization import normalize_location, normalize_title
from tests.fakes import FakeProfile


def make_profile(
    *,
    target_roles: list[str] | None = None,
    skills: list[str] | None = None,
    years: float | None = 4.0,
    locations: list[str] | None = None,
    remote_pref: RemotePreference = RemotePreference.ANY,
    minimum_salary: int | None = None,
    preferred_salary: int | None = None,
    salary_currency: str = "INR",
    industries: list[str] | None = None,
    preferred_companies: list[str] | None = None,
    excluded_companies: list[str] | None = None,
) -> FakeProfile:
    profile = FakeProfile(id=uuid.uuid4().hex, userId="u1")
    profile.targetRoles = target_roles or []
    profile.yearsOfExperience = years
    profile.preferredLocations = locations or []
    profile.remotePreference = remote_pref
    profile.minimumSalary = minimum_salary
    profile.preferredSalary = preferred_salary
    profile.salaryCurrency = salary_currency
    profile.industries = industries or []
    profile.preferredCompanies = preferred_companies or []
    profile.excludedCompanies = excluded_companies or []
    profile.skills = [
        SimpleNamespace(
            skill=SimpleNamespace(name=name), proficiency="ADVANCED", yearsOfExperience=3.0
        )
        for name in (skills or [])
    ]
    return profile


def make_match_job(
    *,
    job_id: str | None = None,
    title: str = "Backend Engineer",
    company: str = "Acme",
    location: str | None = "Bengaluru, India",
    description: str | None = "Build APIs with python and postgres",
    remote: bool = False,
    hybrid: bool = False,
    experience_min: float | None = None,
    experience_max: float | None = None,
    salary_max: int | None = None,
    salary_currency: str | None = None,
    analysis: SimpleNamespace | None = None,
    company_id: str | None = None,
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
        description=description,
        remote=remote,
        hybrid=hybrid,
        experienceMin=experience_min,
        experienceMax=experience_max,
        salaryMin=None,
        salaryMax=salary_max,
        salaryCurrency=salary_currency,
        deletedAt=None,
        createdAt=now,
        analysis=analysis,
    )


@dataclass
class FakeMatchRow:
    id: str
    userId: str
    jobId: str
    overallScore: float = 0.0
    roleScore: float | None = None
    skillScore: float | None = None
    experienceScore: float | None = None
    locationScore: float | None = None
    salaryScore: float | None = None
    workModeScore: float | None = None
    industryScore: float | None = None
    companyScore: float | None = None
    watchlistScore: float | None = None
    recommendation: Any = None
    whyMatch: str | None = None
    missingSkills: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    scoringVersion: str | None = None
    aiModel: str | None = None
    promptVersion: str | None = None
    feedback: MatchFeedback | None = None
    feedbackAt: datetime | None = None
    job: Any = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))
    updatedAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeJobMatchRepository:
    def __init__(self, jobs_by_id: dict[str, Any] | None = None) -> None:
        self.rows: dict[tuple[str, str], FakeMatchRow] = {}
        self.jobs_by_id = jobs_by_id or {}

    async def get_by_user_job(self, user_id: str, job_id: str) -> FakeMatchRow | None:
        return self.rows.get((user_id, job_id))

    async def upsert_for_user_job(
        self, user_id: str, job_id: str, data: dict[str, Any]
    ) -> FakeMatchRow:
        row = self.rows.get((user_id, job_id))
        if row is None:
            row = FakeMatchRow(id=uuid.uuid4().hex, userId=user_id, jobId=job_id)
            self.rows[(user_id, job_id)] = row
        for key, value in data.items():
            setattr(row, key, value)  # feedback never in data => preserved
        row.updatedAt = datetime.now(UTC)
        row.job = self.jobs_by_id.get(job_id)
        return row

    async def set_feedback(self, match_id: str, feedback: MatchFeedback) -> FakeMatchRow:
        row = next(r for r in self.rows.values() if r.id == match_id)
        row.feedback = feedback
        row.feedbackAt = datetime.now(UTC)
        return row

    async def list_ranked_for_user(
        self, user_id: str, *, limit: int, offset: int, min_score: float
    ) -> tuple[list[FakeMatchRow], int]:
        rows = [
            r
            for r in self.rows.values()
            if r.userId == user_id
            and r.overallScore >= min_score
            and r.feedback != MatchFeedback.NOT_RELEVANT
            and (r.job is None or r.job.deletedAt is None)
        ]
        rows.sort(key=lambda r: r.overallScore, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def find_unmatched_job_ids(
        self, user_id: str, scoring_version: str, *, limit: int
    ) -> list[str]:
        result = []
        for job_id, job in self.jobs_by_id.items():
            if job.deletedAt is not None:
                continue
            row = self.rows.get((user_id, job_id))
            if row is None or row.scoringVersion != scoring_version:
                result.append(job_id)
        return result[:limit]


class FakeProfileRepoForMatching:
    def __init__(self, profile: FakeProfile) -> None:
        self.profile = profile

    async def get_by_user_id(self, user_id: str) -> FakeProfile:
        return self.profile

    async def upsert_for_user(self, user_id: str, data: dict[str, Any]) -> FakeProfile:
        return self.profile


class FakeAnalysisRepoForMatching:
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    async def get_by_job_id(self, job_id: str):
        return self.rows.get(job_id)


class FakeJobLookup:
    def __init__(self, jobs_by_id: dict[str, Any]) -> None:
        self.jobs_by_id = jobs_by_id

    async def get_by_id(self, job_id: str):
        return self.jobs_by_id.get(job_id)

    async def find_candidates_by_company(self, company_id: str, *, limit: int):
        rows = [
            job
            for job in self.jobs_by_id.values()
            if getattr(job, "companyId", None) == company_id
        ]
        return rows[:limit]


class FakeWatchlistRepoForMatching:
    """Rows shaped like prisma CompanyWatchlist with the company included."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []

    async def list_for_user(self, user_id: str) -> list[Any]:
        return [row for row in self.rows if row.userId == user_id]


def make_watchlist_row(
    *,
    user_id: str = "u1",
    company_id: str = "c1",
    company_name: str = "Acme",
    priority: str = "HIGH",
    preferred_roles: list[str] | None = None,
    excluded_roles: list[str] | None = None,
) -> SimpleNamespace:
    from app.utils.normalization import normalize_company

    return SimpleNamespace(
        id=uuid.uuid4().hex,
        userId=user_id,
        companyId=company_id,
        priority=priority,
        preferredRoles=preferred_roles or [],
        excludedRoles=excluded_roles or [],
        notes=None,
        company=SimpleNamespace(
            id=company_id, name=company_name, normalizedName=normalize_company(company_name)
        ),
    )
