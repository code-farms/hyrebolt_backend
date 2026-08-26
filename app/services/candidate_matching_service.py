from collections.abc import Sequence
from typing import Any

from app.core.logging import get_logger
from app.db.generated.models import CompanyWatchlist, Job, JobMatch, User
from app.models import MatchFeedback, MatchRecommendation
from app.repositories import (
    CompanyWatchlistRepository,
    JobAnalysisRepository,
    JobMatchRepository,
    JobRepository,
    ProfileRepository,
)
from app.schemas.analysis import JobAnalysisResult
from app.services.ai_matcher import MATCH_PROMPT_VERSION, AIMatcher
from app.services.rule_based_matcher import SCORING_VERSION, RuleBasedMatcher, WatchlistEntry
from app.utils.normalization import normalize_company

logger = get_logger(__name__)


def recommendation_from_score(overall: float) -> MatchRecommendation:
    """Deterministic fallback bands, used whenever the AI layer is down —
    the pipeline never depends on the AI being available."""
    if overall >= 90:
        return MatchRecommendation.MUST_APPLY
    if overall >= 75:
        return MatchRecommendation.STRONG_MATCH
    if overall >= 55:
        return MatchRecommendation.CONSIDER
    if overall >= 35:
        return MatchRecommendation.LOW_PRIORITY
    return MatchRecommendation.IGNORE


def to_watchlist_entries(rows: Sequence[CompanyWatchlist]) -> tuple[WatchlistEntry, ...]:
    entries: list[WatchlistEntry] = []
    for row in rows:
        company = getattr(row, "company", None)
        normalized = (
            company.normalizedName
            if company is not None and getattr(company, "normalizedName", None)
            else normalize_company(getattr(company, "name", "") or "")
        )
        priority = getattr(row.priority, "value", row.priority)
        entries.append(
            WatchlistEntry(
                companyId=row.companyId,
                normalizedName=normalized,
                priority=str(priority),
                preferredRoles=tuple(row.preferredRoles or []),
                excludedRoles=tuple(row.excludedRoles or []),
            )
        )
    return tuple(entries)


class CandidateMatchingService:
    def __init__(
        self,
        matcher: RuleBasedMatcher,
        ai_matcher: AIMatcher,
        matches: JobMatchRepository,
        profiles: ProfileRepository,
        analyses: JobAnalysisRepository,
        jobs: JobRepository,
        watchlists: CompanyWatchlistRepository | None = None,
    ) -> None:
        self._matcher = matcher
        self._ai_matcher = ai_matcher
        self._matches = matches
        self._profiles = profiles
        self._analyses = analyses
        self._jobs = jobs
        self._watchlists = watchlists

    async def match_job(
        self,
        user: User,
        job: Job,
        *,
        force: bool = False,
        watchlist: Sequence[WatchlistEntry] | None = None,
    ) -> JobMatch:
        if not force:
            cached = await self._matches.get_by_user_job(user.id, job.id)
            if (
                cached is not None
                and cached.scoringVersion == SCORING_VERSION
                and cached.promptVersion in (MATCH_PROMPT_VERSION, None)
            ):
                return cached

        profile = await self._profiles.get_by_user_id(user.id)
        if profile is None:
            profile = await self._profiles.upsert_for_user(user.id, {})

        if watchlist is None:
            watchlist = await self._load_watchlist(user.id)
        analysis = await self._load_analysis(job)
        overall, components = self._matcher.score(profile, job, analysis, watchlist)

        data: dict[str, Any] = {
            "overallScore": overall,
            "roleScore": components.role,
            "skillScore": components.skill,
            "experienceScore": components.experience,
            "locationScore": components.location,
            "salaryScore": components.salary,
            "workModeScore": components.workMode,
            "industryScore": components.industry,
            "companyScore": components.company,
            "watchlistScore": components.watchlist,
            "scoringVersion": SCORING_VERSION,
            "recommendation": recommendation_from_score(overall),
            "whyMatch": None,
            "missingSkills": [],
            "strengths": [],
            "concerns": [],
            "aiModel": None,
            "promptVersion": None,
        }

        ai = await self._ai_matcher.explain(profile, job, analysis, components, overall)
        if ai is not None:
            result, model = ai
            data.update(
                {
                    "recommendation": result.recommendation
                    or recommendation_from_score(overall),
                    "whyMatch": result.whyMatch,
                    "missingSkills": result.missingSkills,
                    "strengths": result.strengths,
                    "concerns": result.concerns,
                    "aiModel": model,
                    "promptVersion": MATCH_PROMPT_VERSION,
                }
            )

        row = await self._matches.upsert_for_user_job(user.id, job.id, data)
        logger.info(
            "job_matched",
            job_id=job.id,
            user_id=user.id,
            overall=overall,
            recommendation=str(data["recommendation"]),
            ai=ai is not None,
        )
        return row

    async def ensure_matches_for_user(self, user: User, *, limit: int) -> int:
        """Batch hook (Phase 9's match_jobs task): score jobs lacking a
        current-version match. Per-job failures are logged and skipped."""
        job_ids = await self._matches.find_unmatched_job_ids(
            user.id, SCORING_VERSION, limit=limit
        )
        watchlist = await self._load_watchlist(user.id)
        matched = 0
        for job_id in job_ids:
            job = await self._jobs.get_by_id(job_id)
            if job is None:
                continue
            try:
                await self.match_job(user, job, watchlist=watchlist)
                matched += 1
            except Exception as exc:  # noqa: BLE001 - batch must survive one bad job
                logger.warning("job_match_failed", job_id=job_id, error=str(exc))
        return matched

    async def rescore_company(self, user: User, company_id: str, *, limit: int) -> int:
        """Phase 13: a watchlist change re-scores this user's matches for the
        company right away (bounded); the nightly batch covers the rest."""
        jobs = await self._jobs.find_candidates_by_company(company_id, limit=limit)
        watchlist = await self._load_watchlist(user.id)
        rescored = 0
        for job in jobs:
            if job.deletedAt is not None:
                continue
            try:
                await self.match_job(user, job, force=True, watchlist=watchlist)
                rescored += 1
            except Exception as exc:  # noqa: BLE001 - one bad job must not abort the rest
                logger.warning("job_rescore_failed", job_id=job.id, error=str(exc))
        return rescored

    async def record_feedback(
        self, user: User, job: Job, feedback: MatchFeedback
    ) -> JobMatch:
        match = await self._matches.get_by_user_job(user.id, job.id)
        if match is None:
            match = await self.match_job(user, job)
        return await self._matches.set_feedback(match.id, feedback)

    async def _load_watchlist(self, user_id: str) -> tuple[WatchlistEntry, ...]:
        if self._watchlists is None:
            return ()
        return to_watchlist_entries(await self._watchlists.list_for_user(user_id))

    async def _load_analysis(self, job: Job) -> JobAnalysisResult | None:
        row = getattr(job, "analysis", None)
        if row is None:
            row = await self._analyses.get_by_job_id(job.id)
        if row is None:
            return None
        try:
            return JobAnalysisResult.model_validate(row.analysis)
        except Exception:  # noqa: BLE001 - a corrupt stored analysis must not break matching
            logger.warning("stored_analysis_invalid", job_id=job.id)
            return None
