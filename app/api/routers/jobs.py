from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import (
    CandidateMatchingServiceDep,
    CurrentUserDep,
    JobAnalysisServiceDep,
    JobRepositoryDep,
    PreferenceSignalServiceDep,
    RankingServiceDep,
    SavedJobRepositoryDep,
    SettingsDep,
    rate_limit,
)
from app.core.exceptions import NotFoundError
from app.models import PreferenceSignalKind
from app.repositories.job_repository import JobFilters
from app.schemas.analysis import JobAnalysisOut
from app.schemas.job import JobListOut, JobOut, analysis_out, job_out
from app.schemas.match import (
    FeedbackIn,
    HideIn,
    MatchOut,
    RecommendedListOut,
    match_out,
    recommended_out,
)
from app.schemas.preferences import LearnedPreferencesOut, learned_preferences_out

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("", response_model=JobListOut)
async def list_jobs(
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    ranking: RankingServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None, max_length=64),
    location: str | None = Query(default=None, max_length=120),
    remote: bool | None = Query(default=None),
    company: str | None = Query(default=None, max_length=120),
    minSalary: int | None = Query(default=None, ge=0),
    maxExperience: float | None = Query(default=None, ge=0, le=60),
    skills: str | None = Query(
        default=None, max_length=300, description="comma-separated terms (max 10)"
    ),
    datePosted: int | None = Query(default=None, ge=1, le=90),
    minScore: float | None = Query(default=None, ge=0, le=100),
    sort: Literal["recent", "score"] = Query(default="recent"),
) -> JobListOut:
    filters = JobFilters(
        source=source,
        location=location,
        remote=remote,
        company=company,
        min_salary=minSalary,
        max_experience=maxExperience,
        # Each term is an unindexed ILIKE over title+description: cap the fan-out.
        skills=tuple(term.strip() for term in (skills or "").split(",") if term.strip())[:10],
        date_posted_days=datePosted,
    )
    if sort == "score" or minScore is not None:
        # Personalised order (Phase 16) over the base-score candidates; nothing
        # is hidden in the browse view.
        ranked, total = await ranking.ranked_jobs(
            user, filters, min_score=minScore or 0, limit=limit, offset=offset
        )
        items = []
        for entry in ranked:
            if entry.match.job is None:
                continue
            out = job_out(entry.match.job)
            out.ranking = entry.ranking
            items.append(out)
    else:
        rows, total = await jobs.list_filtered(
            user.id, filters, limit=limit, offset=offset
        )
        items = [job_out(row) for row in rows]
    return JobListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/saved", response_model=JobListOut)
async def list_saved_jobs(
    user: CurrentUserDep,
    saved: SavedJobRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    rows, total = await saved.list_for_user(user.id, limit=limit, offset=offset)
    items = []
    for row in rows:
        if row.job is None:
            continue
        out = job_out(row.job)
        out.saved = True  # by definition; the include doesn't carry savedBy here
        items.append(out)
    return JobListOut(items=items, total=total, limit=limit, offset=offset)


# NOTE: static paths must be declared before the /{job_id} routes.
@router.get("/recommended", response_model=RecommendedListOut)
async def recommended_jobs(
    user: CurrentUserDep,
    matching: CandidateMatchingServiceDep,
    ranking: RankingServiceDep,
    settings: SettingsDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    minScore: float = Query(default=0, ge=0, le=100),
) -> RecommendedListOut:
    # Score any not-yet-matched jobs first (bounded; Phase 9 moves this batch
    # to the background workers), then return the ranked list.
    await matching.ensure_matches_for_user(user, limit=settings.match_batch_limit)
    rows, total = await ranking.recommended(
        user, limit=limit, offset=offset, min_score=minScore
    )
    return RecommendedListOut(
        items=[recommended_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    saved: SavedJobRepositoryDep,
) -> JobOut:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    out = job_out(job)
    out.saved = await saved.is_saved(user.id, job_id)
    return out


@router.post("/{job_id}/save", response_model=JobOut)
async def save_job(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    saved: SavedJobRepositoryDep,
    signals: PreferenceSignalServiceDep,
) -> JobOut:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    await saved.save(user.id, job_id)  # idempotent upsert
    await signals.record(user, job, PreferenceSignalKind.SAVE)  # Phase 16: saving teaches
    out = job_out(job)
    out.saved = True
    return out


@router.delete("/{job_id}/save", response_model=JobOut)
async def unsave_job(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    saved: SavedJobRepositoryDep,
    signals: PreferenceSignalServiceDep,
) -> JobOut:
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    await saved.unsave(user.id, job_id)  # idempotent
    await signals.remove(user, job, PreferenceSignalKind.SAVE)
    out = job_out(job)
    out.saved = False
    return out


@router.post("/{job_id}/hide", response_model=LearnedPreferencesOut)
async def hide_job(
    job_id: str,
    payload: HideIn,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    signals: PreferenceSignalServiceDep,
) -> LearnedPreferencesOut:
    """Phase 16: stop recommending this company (or roles like this one).
    Reversible from the preferences page."""
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    await signals.record(user, job, payload.to_signal())
    return learned_preferences_out(await signals.learn(user))


@router.post(
    "/{job_id}/analyze",
    response_model=JobAnalysisOut,
    dependencies=[rate_limit("ai", "ai_rate_limit_per_minute")],
)
async def analyze_job(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    analysis_service: JobAnalysisServiceDep,
) -> JobAnalysisOut:
    """Run (or return the cached) AI analysis for a job."""
    job = await jobs.get_by_id(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    row = await analysis_service.analyze_job(job)
    return analysis_out(row)


@router.get(
    "/{job_id}/match",
    response_model=MatchOut,
    dependencies=[rate_limit("ai", "ai_rate_limit_per_minute")],
)
async def get_job_match(
    job_id: str,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    matching: CandidateMatchingServiceDep,
) -> MatchOut:
    """Compute (or return the cached) match between the caller and a job."""
    job = await jobs.get_with_listings(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    match = await matching.match_job(user, job)
    return match_out(match)


@router.post("/{job_id}/feedback", response_model=MatchOut)
async def job_feedback(
    job_id: str,
    payload: FeedbackIn,
    user: CurrentUserDep,
    jobs: JobRepositoryDep,
    matching: CandidateMatchingServiceDep,
    signals: PreferenceSignalServiceDep,
) -> MatchOut:
    job = await jobs.get_by_id(job_id)
    if job is None or job.deletedAt is not None:
        raise NotFoundError("Job not found.")
    match = await matching.record_feedback(user, job, payload.to_enum())
    kind, weight = payload.to_signal()  # Phase 16: feedback also teaches
    await signals.record(user, job, kind, weight=weight)
    return match_out(match)
