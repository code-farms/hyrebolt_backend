"""Personalised, interpretable ranking (Phase 16).

The deterministic match score (Phase 8) stays the base. Learned preferences,
freshness, company standing and direct feedback add small, capped deltas —
each with a sentence explaining it — and the result is computed on read from
the user's own signals, never stored. With no signal service wired in, the
service degrades to the Phase 8 behaviour (base order, empty explanations)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.generated.models import JobMatch, User
from app.models import MatchFeedback
from app.repositories import JobMatchRepository, JobRepository
from app.repositories.job_repository import JobFilters
from app.schemas.analysis import JobAnalysisResult
from app.schemas.match import RankedMatch, RankingOut, base_only_ranking
from app.services.preference_signal_service import (
    Affinity,
    LearnedPreferences,
    PreferenceSignalService,
    derive_work_mode,
)
from app.utils.normalization import normalize_company, normalize_skill

logger = get_logger(__name__)

MAX_EXPLANATIONS = 3


@dataclass(frozen=True)
class RankingWeights:
    candidate_limit: int = 300
    preference_cap: float = 15.0
    role_cap: float = 6.0
    skill_cap: float = 5.0
    company_pref_cap: float = 4.0
    location_cap: float = 3.0
    work_mode_cap: float = 3.0
    freshness_cap: float = 6.0
    company_boost_cap: float = 5.0
    company_penalty: float = 10.0
    feedback_boost_cap: float = 5.0
    feedback_penalty: float = 15.0
    role_hide_similarity: float = 0.75
    role_boost_similarity: float = 0.5

    @classmethod
    def from_settings(cls, settings: Settings) -> "RankingWeights":
        return cls(
            candidate_limit=settings.ranking_candidate_limit,
            preference_cap=settings.ranking_preference_cap,
            freshness_cap=settings.ranking_freshness_cap,
            company_boost_cap=settings.ranking_company_boost_cap,
            company_penalty=settings.ranking_company_penalty,
            feedback_boost_cap=settings.ranking_feedback_boost_cap,
            feedback_penalty=settings.ranking_feedback_penalty,
            role_hide_similarity=settings.ranking_role_hide_similarity,
        )


DEFAULT_WEIGHTS = RankingWeights()

_VERB: dict[str, tuple[str, str]] = {
    # kind -> (positive phrasing, negative phrasing) for explanation sentences
    "APPLY": ("applied to", "applied to"),
    "SAVE": ("saved", "saved"),
    "LIKE": ("liked", "liked"),
    "DISLIKE": ("disliked", "disliked"),
    "NOT_RELEVANT": ("dismissed", "dismissed"),
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _strength(weight: float) -> float:
    """Three likes ≈ one apply ≈ full strength; saturates instead of running away."""
    return _clamp(weight / 3.0, -1.0, 1.0)


def _tokens(text: str) -> set[str]:
    return {token for token in text.split() if token}


def token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_KIND_STRENGTH = {"APPLY": 3, "NOT_RELEVANT": 2, "SAVE": 1.5, "LIKE": 1, "DISLIKE": 1}


def _dominant_kind(affinity: Affinity) -> str:
    """The action that best explains this affinity: most frequent, ties broken
    by the heavier signal (applying beats saving beats liking)."""
    if not affinity.by_kind:
        return "LIKE"
    positive = {k: n for k, n in affinity.by_kind.items() if k in ("APPLY", "SAVE", "LIKE")}
    negative = {k: n for k, n in affinity.by_kind.items() if k in ("DISLIKE", "NOT_RELEVANT")}
    pool = positive if affinity.weight > 0 else negative
    if not pool:
        pool = affinity.by_kind
    return max(pool.items(), key=lambda item: (item[1], _KIND_STRENGTH.get(item[0], 0)))[0]


def _sentence(affinity: Affinity, noun: str) -> str:
    direction = "higher" if affinity.weight > 0 else "lower"
    kind = _dominant_kind(affinity)
    verb = _VERB.get(kind, ("liked", "liked"))[0]
    count = affinity.by_kind.get(kind, affinity.count)
    qualifier = "frequently " if count >= 3 else ""
    times = f"{count} " if 1 < count < 3 else ""
    return f"Ranked {direction} because you {qualifier}{verb} {times}{noun}"


def _job_analysis(match: JobMatch) -> JobAnalysisResult | None:
    job = match.job
    row = getattr(job, "analysis", None) if job is not None else None
    if row is None:
        return None
    try:
        return JobAnalysisResult.model_validate(row.analysis)
    except Exception:  # noqa: BLE001 - a corrupt stored analysis must not break ranking
        return None


def _age_days(match: JobMatch, now: datetime) -> float | None:
    job = match.job
    if job is None:
        return None
    reference = getattr(job, "postedAt", None) or getattr(job, "discoveredAt", None)
    if reference is None:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return max(0.0, (now - reference).total_seconds() / 86400)


def score_match(
    match: JobMatch,
    prefs: LearnedPreferences,
    *,
    now: datetime,
    weights: RankingWeights = DEFAULT_WEIGHTS,
    exclude: bool = True,
) -> RankingOut | None:
    """Personalised score for one candidate, or None when it must be excluded
    (hidden company / hidden role). Pure: no I/O."""
    job = match.job
    base = float(match.overallScore)
    role_key = (getattr(job, "normalizedTitle", None) or "") if job else ""
    company_key = normalize_company(job.companyName) if job and job.companyName else ""
    reasons: list[tuple[float, str]] = []  # (magnitude, sentence)

    if exclude:
        if company_key and any(h.key == company_key for h in prefs.hidden_companies):
            return None
        if role_key and any(
            hidden.key == role_key
            or token_jaccard(role_key, hidden.key) >= weights.role_hide_similarity
            for hidden in prefs.hidden_roles
        ):
            return None

    analysis = _job_analysis(match)

    # ── preference (learned) ─────────────────────────────────────────────
    preference = 0.0
    if not prefs.is_empty:
        # roles: exact key first, else the most similar learned role
        role_aff = prefs.roles.get(role_key) if role_key else None
        similarity = 1.0
        if role_aff is None and role_key:
            best: tuple[float, Affinity] | None = None
            for key, affinity in prefs.roles.items():
                sim = token_jaccard(role_key, key)
                if sim >= weights.role_boost_similarity and (best is None or sim > best[0]):
                    best = (sim, affinity)
            if best is not None:
                similarity, role_aff = best
        if role_aff is not None:
            delta = _clamp(
                _strength(role_aff.weight) * similarity * weights.role_cap,
                -weights.role_cap,
                weights.role_cap,
            )
            preference += delta
            reasons.append((abs(delta), _sentence(role_aff, f"roles like ‘{role_aff.label}’")))

        # skills
        if analysis is not None and prefs.skills:
            job_skills = {normalize_skill(s) for s in [*analysis.skillsRequired, *analysis.techStack]}
            hits = [prefs.skills[key] for key in job_skills if key in prefs.skills]
            if hits:
                total = _clamp(sum(_strength(a.weight) for a in hits), -1.0, 1.0)
                delta = total * weights.skill_cap
                preference += delta
                top = sorted(hits, key=lambda a: abs(a.weight), reverse=True)[:3]
                strongest = max(hits, key=lambda a: abs(a.weight))
                reasons.append(
                    (abs(delta), _sentence(strongest, "jobs needing " + ", ".join(a.label for a in top)))
                )

        # company
        company_aff = prefs.companies.get(company_key) if company_key else None
        if company_aff is not None:
            delta = _strength(company_aff.weight) * weights.company_pref_cap
            preference += delta
            reasons.append((abs(delta), _sentence(company_aff, f"jobs at {company_aff.label}")))

        # location
        location = getattr(job, "normalizedLocation", None) if job else None
        if location and prefs.locations:
            best_loc: Affinity | None = None
            for key, affinity in prefs.locations.items():
                matches_location = bool(key) and (key in location or location in key)
                if matches_location and (
                    best_loc is None or abs(affinity.weight) > abs(best_loc.weight)
                ):
                    best_loc = affinity
            if best_loc is not None:
                delta = _strength(best_loc.weight) * weights.location_cap
                preference += delta
                reasons.append((abs(delta), _sentence(best_loc, f"jobs in {best_loc.label}")))

        # work mode
        mode = derive_work_mode(job, analysis) if job else None
        mode_aff = prefs.work_modes.get(mode) if mode else None
        if mode_aff is not None:
            delta = _strength(mode_aff.weight) * weights.work_mode_cap
            preference += delta
            reasons.append((abs(delta), _sentence(mode_aff, f"{mode.lower()} roles")))

    preference = _clamp(preference, -weights.preference_cap, weights.preference_cap)

    # ── freshness ────────────────────────────────────────────────────────
    freshness = 0.0
    age = _age_days(match, now)
    if age is not None:
        scale = weights.freshness_cap / 6.0
        if age <= 2:
            freshness = 6.0 * scale
        elif age <= 7:
            freshness = 4.0 * scale
        elif age <= 14:
            freshness = 2.0 * scale
        if freshness > 0:
            days = int(age)
            when = "today" if days == 0 else ("yesterday" if days == 1 else f"{days} days ago")
            source = "Posted" if getattr(job, "postedAt", None) else "Discovered"
            reasons.append((freshness, f"{source} {when}"))

    # ── company standing (watchlist / profile) ───────────────────────────
    company = 0.0
    watchlist = getattr(match, "watchlistScore", None)
    if watchlist is not None:
        scale = weights.company_boost_cap / 5.0
        boost = (5.0 if watchlist >= 90 else 3.0 if watchlist >= 75 else 2.0) * scale
        company += boost
        reasons.append((boost, "Company is on your watchlist"))
    company_component = getattr(match, "companyScore", None)
    if company_component == 100:
        company += 3.0 * (weights.company_boost_cap / 5.0)
        reasons.append((3.0, "Preferred company in your profile"))
    elif company_component == 0:
        company -= weights.company_penalty
        reasons.append((weights.company_penalty, "Excluded company in your profile"))
    company = _clamp(company, -weights.company_penalty, weights.company_boost_cap)

    # ── direct feedback on this job ──────────────────────────────────────
    feedback = 0.0
    raw_verdict = getattr(match, "feedback", None)
    verdict = str(getattr(raw_verdict, "value", raw_verdict)) if raw_verdict else None
    if verdict == MatchFeedback.POSITIVE:
        feedback = weights.feedback_boost_cap
        reasons.append((feedback, "You marked this a good match"))
    elif verdict == MatchFeedback.INTERESTED:
        feedback = weights.feedback_boost_cap * 0.6
        reasons.append((feedback, "You marked this as interesting"))
    elif verdict == MatchFeedback.NEGATIVE:
        feedback = -weights.feedback_penalty
        reasons.append((weights.feedback_penalty, "You marked this a poor match"))

    final = _clamp(base + preference + freshness + company + feedback, 0.0, 100.0)
    reasons.sort(key=lambda item: item[0], reverse=True)
    return RankingOut(
        finalScore=round(final, 1),
        baseScore=round(base, 1),
        preferenceScore=round(preference, 1),
        freshnessScore=round(freshness, 1),
        companyScore=round(company, 1),
        feedbackScore=round(feedback, 1),
        explanations=[text for _, text in reasons[:MAX_EXPLANATIONS]],
    )


class RankingService:
    def __init__(
        self,
        matches: JobMatchRepository,
        *,
        jobs: JobRepository | None = None,
        signals: PreferenceSignalService | None = None,
        weights: RankingWeights = DEFAULT_WEIGHTS,
    ) -> None:
        self._matches = matches
        self._jobs = jobs
        self._signals = signals
        self._weights = weights

    async def recommended(
        self, user: User, *, limit: int, offset: int, min_score: float
    ) -> tuple[list[RankedMatch], int]:
        """Personalised feed: the top `candidate_limit` matches by base score
        are re-scored and re-ordered here; `total` counts those candidates."""
        if self._signals is None:  # Phase 8 behaviour
            rows, total = await self._matches.list_ranked_for_user(
                user.id, limit=limit, offset=offset, min_score=min_score
            )
            return [RankedMatch(match=row, ranking=base_only_ranking(row)) for row in rows], total

        candidates = await self._matches.list_candidates_for_user(
            user.id, min_score=min_score, limit=self._weights.candidate_limit
        )
        prefs = await self._signals.learn(user)
        ranked = self._rank(candidates, prefs, exclude=True)
        return ranked[offset : offset + limit], len(ranked)

    async def ranked_jobs(
        self,
        user: User,
        filters: JobFilters,
        *,
        min_score: float,
        limit: int,
        offset: int,
    ) -> tuple[list[RankedMatch], int]:
        """Browse view (`/jobs?sort=score`): personalised order, but nothing is
        hidden and `total` stays the database count."""
        assert self._jobs is not None, "ranked_jobs needs a JobRepository"
        rows, total = await self._jobs.list_by_score(
            user.id,
            filters,
            min_score=min_score,
            limit=self._weights.candidate_limit,
            offset=0,
        )
        prefs = await self._signals.learn(user) if self._signals else LearnedPreferences()
        ranked = self._rank(rows, prefs, exclude=False)
        return ranked[offset : offset + limit], total

    def _rank(
        self, rows: Sequence[JobMatch], prefs: LearnedPreferences, *, exclude: bool
    ) -> list[RankedMatch]:
        now = datetime.now(UTC)
        ranked: list[RankedMatch] = []
        dropped = 0
        for row in rows:
            ranking = score_match(row, prefs, now=now, weights=self._weights, exclude=exclude)
            if ranking is None:
                dropped += 1
                continue
            ranked.append(RankedMatch(match=row, ranking=ranking))
        ranked.sort(key=lambda r: (r.ranking.finalScore, r.match.overallScore), reverse=True)
        if dropped:
            logger.info("ranking_excluded", dropped=dropped, kept=len(ranked))
        return ranked
