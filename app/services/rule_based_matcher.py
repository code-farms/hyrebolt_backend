"""Deterministic candidate↔job scoring (Phase 8).

The rule scores are the system of record for ranking; the AI layer only adds
explanations. Every component is 0–100. Unknown data scores a neutral 50 —
never a fabricated penalty or boost."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.config import Settings
from app.db.generated.models import Job, UserProfile
from app.models import RemotePreference
from app.schemas.analysis import JobAnalysisResult
from app.services.job_identity_service import JobIdentityService
from app.utils.normalization import normalize_company, normalize_location, normalize_title

# Bump when the scoring rules change: stored matches from older versions are
# treated as stale and re-scored.
SCORING_VERSION = "rules-v2"

NEUTRAL = 50.0

# Phase 13 watchlist component: base score by priority. A preferred-role hit
# adds 10, a listed-but-unmatched preferred role subtracts 15, an excluded role
# zeroes the component.
WATCHLIST_BASE: dict[str, float] = {"HIGH": 90.0, "MEDIUM": 75.0, "LOW": 60.0}
WATCHLIST_PREFERRED_BONUS = 10.0
WATCHLIST_UNPREFERRED_PENALTY = 15.0
ROLE_MATCH_THRESHOLD = 0.6


@dataclass(frozen=True)
class WatchlistEntry:
    """Prisma-free view of a CompanyWatchlist row, so the matcher (and its
    tests) never depend on generated models."""

    companyId: str
    normalizedName: str
    priority: str  # "HIGH" | "MEDIUM" | "LOW" — Prisma enums arrive as str
    preferredRoles: tuple[str, ...] = ()
    excludedRoles: tuple[str, ...] = ()


@dataclass
class ComponentScores:
    role: float
    skill: float
    experience: float
    location: float
    salary: float
    workMode: float
    industry: float
    company: float
    # None when the company is not on the user's watchlist: "no signal", so the
    # weighted mean treats it as NEUTRAL and the UI can hide the badge.
    watchlist: float | None = None


class RuleBasedMatcher:
    def __init__(self, settings: Settings, identity: JobIdentityService | None = None) -> None:
        self._settings = settings
        self._identity = identity or JobIdentityService()

    def score(
        self,
        profile: UserProfile,
        job: Job,
        analysis: JobAnalysisResult | None,
        watchlist: Sequence[WatchlistEntry] = (),
    ) -> tuple[float, ComponentScores]:
        components = ComponentScores(
            role=self._role_score(profile, job, analysis),
            skill=self._skill_score(profile, job, analysis),
            experience=self._experience_score(profile, job, analysis),
            location=self._location_score(profile, job),
            salary=self._salary_score(profile, job, analysis),
            workMode=self._work_mode_score(profile, job, analysis),
            industry=self._industry_score(profile, analysis),
            company=self._company_score(profile, job),
            watchlist=self._watchlist_score(job, analysis, watchlist),
        )
        s = self._settings
        watchlist_value = components.watchlist if components.watchlist is not None else NEUTRAL
        overall = (
            s.match_weight_role * components.role
            + s.match_weight_skills * components.skill
            + s.match_weight_experience * components.experience
            + s.match_weight_location * components.location
            + s.match_weight_salary * components.salary
            + s.match_weight_work_mode * components.workMode
            + s.match_weight_industry * components.industry
            + s.match_weight_company * components.company
            + s.match_weight_watchlist * watchlist_value
        )
        total_weight = (
            s.match_weight_role
            + s.match_weight_skills
            + s.match_weight_experience
            + s.match_weight_location
            + s.match_weight_salary
            + s.match_weight_work_mode
            + s.match_weight_industry
            + s.match_weight_company
            + s.match_weight_watchlist
        )
        return round(overall / total_weight, 1) if total_weight else 0.0, components

    def _role_score(
        self, profile: UserProfile, job: Job, analysis: JobAnalysisResult | None
    ) -> float:
        if not profile.targetRoles:
            return NEUTRAL
        job_titles = [job.normalizedTitle]
        if analysis is not None and analysis.title:
            job_titles.append(normalize_title(analysis.title))
        best = max(
            self._identity.title_similarity(normalize_title(role), title)
            for role in profile.targetRoles
            for title in job_titles
        )
        return round(best * 100, 1)

    def _skill_score(
        self, profile: UserProfile, job: Job, analysis: JobAnalysisResult | None
    ) -> float:
        user_skills = {
            (user_skill.skill.name if user_skill.skill else "").strip().casefold()
            for user_skill in profile.skills or []
        }
        user_skills.discard("")
        if not user_skills:
            return NEUTRAL

        if analysis is not None and (analysis.skillsRequired or analysis.skillsPreferred or analysis.techStack):
            required = {s.strip().casefold() for s in analysis.skillsRequired if s.strip()}
            preferred = {
                s.strip().casefold()
                for s in [*analysis.skillsPreferred, *analysis.techStack]
                if s.strip()
            } - required
            total = len(required) * 1.0 + len(preferred) * 0.5
            if total == 0:
                return NEUTRAL
            covered = (
                len(required & user_skills) * 1.0 + len(preferred & user_skills) * 0.5
            )
            return round(covered / total * 100, 1)

        # Fallback: user skills appearing in the raw title/description.
        haystack = f"{job.title} {job.description or ''}".casefold()
        if not haystack.strip():
            return NEUTRAL
        hits = sum(1 for skill in user_skills if skill in haystack)
        return round(min(1.0, hits / max(3, len(user_skills) // 2)) * 100, 1)

    def _experience_score(
        self, profile: UserProfile, job: Job, analysis: JobAnalysisResult | None
    ) -> float:
        years = profile.yearsOfExperience
        minimum = job.experienceMin if job.experienceMin is not None else (
            analysis.experienceMin if analysis else None
        )
        maximum = job.experienceMax if job.experienceMax is not None else (
            analysis.experienceMax if analysis else None
        )
        if years is None or (minimum is None and maximum is None):
            return NEUTRAL
        if minimum is not None and years < minimum:
            return round(max(0.0, 100 - (minimum - years) * 25), 1)
        if maximum is not None and years > maximum:
            return round(max(60.0, 100 - (years - maximum) * 10), 1)
        return 100.0

    def _location_score(self, profile: UserProfile, job: Job) -> float:
        remote_ok = profile.remotePreference in (
            RemotePreference.REMOTE,
            RemotePreference.HYBRID,
            RemotePreference.ANY,
        )
        if job.remote and remote_ok:
            return 100.0
        if job.normalizedLocation and profile.preferredLocations:
            wanted = [normalize_location(loc) for loc in profile.preferredLocations]
            if any(w and (w in job.normalizedLocation or job.normalizedLocation in w) for w in wanted):
                return 100.0
            return 20.0
        return NEUTRAL

    def _salary_score(
        self, profile: UserProfile, job: Job, analysis: JobAnalysisResult | None
    ) -> float:
        salary_max = job.salaryMax
        currency = job.salaryCurrency
        if salary_max is None and analysis is not None and analysis.salary is not None:
            salary_max = analysis.salary.max
            currency = analysis.salary.currency
        if salary_max is None:
            return NEUTRAL
        if currency is not None and currency != profile.salaryCurrency:
            return NEUTRAL  # no FX guessing
        if profile.preferredSalary is not None and salary_max >= profile.preferredSalary:
            return 100.0
        if profile.minimumSalary is not None:
            return 70.0 if salary_max >= profile.minimumSalary else 20.0
        if profile.preferredSalary is not None:
            return 70.0  # below preferred but no hard minimum set
        return NEUTRAL

    def _work_mode_score(
        self, profile: UserProfile, job: Job, analysis: JobAnalysisResult | None
    ) -> float:
        job_mode: str | None = None
        if job.remote:
            job_mode = "REMOTE"
        elif job.hybrid:
            job_mode = "HYBRID"
        elif analysis is not None and analysis.workMode:
            job_mode = analysis.workMode
        if job_mode is None:
            return NEUTRAL

        # Prisma returns enum columns as plain strings at runtime; compare as str.
        preference = str(profile.remotePreference)
        if preference == RemotePreference.ANY:
            return 70.0
        if preference == job_mode:
            return 100.0
        compatible = {("REMOTE", "HYBRID"), ("HYBRID", "REMOTE"), ("HYBRID", "ONSITE")}
        if (preference, job_mode) in compatible:
            return 70.0
        return 0.0

    def _industry_score(
        self, profile: UserProfile, analysis: JobAnalysisResult | None
    ) -> float:
        if analysis is None or not analysis.industry or not profile.industries:
            return NEUTRAL
        industry = analysis.industry.strip().casefold()
        wanted = [entry.strip().casefold() for entry in profile.industries]
        if any(w and (w in industry or industry in w) for w in wanted):
            return 100.0
        return 0.0

    def _company_score(self, profile: UserProfile, job: Job) -> float:
        company = normalize_company(job.companyName)
        excluded = [normalize_company(c) for c in profile.excludedCompanies]
        if any(e and e == company for e in excluded):
            return 0.0
        preferred = [normalize_company(c) for c in profile.preferredCompanies]
        if any(p and p == company for p in preferred):
            return 100.0
        return NEUTRAL

    def _watchlist_score(
        self,
        job: Job,
        analysis: JobAnalysisResult | None,
        watchlist: Sequence[WatchlistEntry],
    ) -> float | None:
        entry = self._watchlist_entry_for(job, watchlist)
        if entry is None:
            return None
        if self._title_matches(job, analysis, entry.excludedRoles):
            return 0.0
        base = WATCHLIST_BASE.get(str(entry.priority), WATCHLIST_BASE["MEDIUM"])
        if not entry.preferredRoles:
            return base
        if self._title_matches(job, analysis, entry.preferredRoles):
            return min(100.0, base + WATCHLIST_PREFERRED_BONUS)
        return base - WATCHLIST_UNPREFERRED_PENALTY

    @staticmethod
    def _watchlist_entry_for(
        job: Job, watchlist: Sequence[WatchlistEntry]
    ) -> WatchlistEntry | None:
        if not watchlist:
            return None
        company_id = getattr(job, "companyId", None)
        if company_id is not None:
            for entry in watchlist:
                if entry.companyId == company_id:
                    return entry
        # Legacy jobs whose company resolution failed have no companyId.
        company = normalize_company(job.companyName)
        for entry in watchlist:
            if company and entry.normalizedName == company:
                return entry
        return None

    def _title_matches(
        self, job: Job, analysis: JobAnalysisResult | None, roles: Sequence[str]
    ) -> bool:
        if not roles:
            return False
        titles = [job.normalizedTitle]
        if analysis is not None and analysis.title:
            titles.append(normalize_title(analysis.title))
        for role in roles:
            wanted = normalize_title(role)
            if not wanted:
                continue
            for title in titles:
                if wanted in title or title in wanted:
                    return True
                if self._identity.title_similarity(wanted, title) >= ROLE_MATCH_THRESHOLD:
                    return True
        return False
