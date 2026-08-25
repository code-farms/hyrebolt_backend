"""Fuzzy duplicate detection (Phase 6).

Runs only on candidates already blocked by company identity (spec signal 3):
the exact signals — canonical URL and source external id — are handled first
by the pipeline's fast path. The score is a weighted sum over a FIXED
denominator (all configured weights): an unavailable signal contributes zero.
That is deliberate — merging requires positive evidence, and two sparse
records agreeing on the little they share must not auto-merge. Policy: never
blind-merge — scores land in one of three bands: auto-merge,
link-without-merging, or new. A title-similarity gate additionally prevents
shared boilerplate from ever matching different roles."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.config import Settings
from app.services.job_identity_service import JobIdentityService
from app.sources.models import NormalizedJob


class JobLike(Protocol):
    """The Job-row fields the scorer reads (satisfied by the Prisma model)."""

    id: str
    normalizedTitle: str
    normalizedLocation: str | None
    description: str | None

    @property
    def postedAt(self) -> object: ...


class DuplicateVerdict(StrEnum):
    DUPLICATE = "duplicate"  # score >= auto-merge threshold
    NEAR_DUPLICATE = "near_duplicate"  # link threshold <= score < auto-merge
    DISTINCT = "distinct"


@dataclass
class DuplicateDecision:
    verdict: DuplicateVerdict
    matched_job_id: str | None = None
    score: float = 0.0


class DuplicateDetectionService:
    def __init__(self, settings: Settings, identity: JobIdentityService | None = None) -> None:
        self._settings = settings
        self._identity = identity or JobIdentityService()

    def score(self, candidate: NormalizedJob, existing: JobLike) -> float:
        identity = self._identity
        signals: list[tuple[float, float | None]] = [
            (
                self._settings.dedup_weight_title,
                identity.title_similarity(candidate.normalizedTitle, existing.normalizedTitle),
            ),
            (
                self._settings.dedup_weight_description,
                identity.description_similarity(candidate.description, existing.description),
            ),
            (
                self._settings.dedup_weight_location,
                identity.location_similarity(
                    candidate.normalizedLocation, existing.normalizedLocation
                ),
            ),
            (
                self._settings.dedup_weight_posted_date,
                identity.posted_date_proximity(candidate.postedAt, existing.postedAt),  # type: ignore[arg-type]
            ),
        ]
        total_weight = sum(weight for weight, _ in signals)
        if total_weight == 0:
            return 0.0
        weighted = sum(weight * value for weight, value in signals if value is not None)
        return weighted / total_weight

    def decide(self, candidate: NormalizedJob, existing_jobs: list[JobLike]) -> DuplicateDecision:
        best_job: JobLike | None = None
        best_score = 0.0
        for existing in existing_jobs:
            # Title gate: shared boilerplate (description/location/date) must
            # never make two different roles look identical.
            title_sim = self._identity.title_similarity(
                candidate.normalizedTitle, existing.normalizedTitle
            )
            if title_sim < self._settings.dedup_min_title_similarity:
                continue
            current = self.score(candidate, existing)
            if current > best_score:
                best_job, best_score = existing, current

        if best_job is None:
            return DuplicateDecision(DuplicateVerdict.DISTINCT)
        if best_score >= self._settings.dedup_auto_merge_threshold:
            return DuplicateDecision(DuplicateVerdict.DUPLICATE, best_job.id, best_score)
        if best_score >= self._settings.dedup_link_threshold:
            return DuplicateDecision(DuplicateVerdict.NEAR_DUPLICATE, best_job.id, best_score)
        return DuplicateDecision(DuplicateVerdict.DISTINCT, None, best_score)
