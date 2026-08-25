"""The spec's dedup scenario matrix: exact duplicates, title variations,
different locations, same company different jobs, similar descriptions,
false positives. Verdicts are asserted alongside the score band so threshold
tuning fails loudly rather than silently flipping behavior."""

import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.duplicate_detection_service import (
    DuplicateDetectionService,
    DuplicateVerdict,
)
from tests.discovery.fakes import FakeJobRow, make_normalized_job

settings = get_settings()
detector = DuplicateDetectionService(settings)

POSTED = datetime(2026, 8, 20, tzinfo=UTC)
DESCRIPTION = (
    "we are looking for a backend engineer to design build and operate the "
    "payment apis that power our merchant platform you will work with python "
    "postgres and redis and own services end to end"
)


def existing_row(
    *,
    title: str = "backend engineer",
    location: str | None = "bengaluru, india",
    description: str | None = DESCRIPTION,
    posted_at: datetime | None = POSTED,
) -> FakeJobRow:
    return FakeJobRow(
        id=uuid.uuid4().hex,
        contentHash="x",
        canonicalUrl=None,
        companyId="c1",
        normalizedTitle=title,
        normalizedLocation=location,
        description=description,
        postedAt=posted_at,
    )


def candidate(**kwargs):
    defaults = {
        "title": "Backend Engineer",
        "location": "Bengaluru, India",
        "description": DESCRIPTION,
        "posted_at": POSTED,
        "company": "Acme",
    }
    defaults.update(kwargs)
    return make_normalized_job(
        source_name="beta",
        external_id=uuid.uuid4().hex,
        title=defaults["title"],
        location=defaults["location"],
        description=defaults["description"],
        posted_at=defaults["posted_at"],
        company=defaults["company"],
        remote=False,
    )


def test_exact_duplicate_scores_one_and_merges() -> None:
    row = existing_row()
    job = candidate()

    score = detector.score(job, row)
    decision = detector.decide(job, [row])

    assert score == 1.0
    assert decision.verdict is DuplicateVerdict.DUPLICATE
    assert decision.matched_job_id == row.id


def test_title_variation_still_merges() -> None:
    row = existing_row(title="sr backend engineer")
    job = candidate(title="Senior Backend Engineer")

    score = detector.score(job, row)
    decision = detector.decide(job, [row])

    assert score >= settings.dedup_auto_merge_threshold
    assert decision.verdict is DuplicateVerdict.DUPLICATE


def test_different_locations_are_distinct_openings() -> None:
    row = existing_row(
        location="pune, india",
        description="own the pune platform team services and mentor engineers on site",
    )
    job = candidate(location="Bengaluru, India")

    score = detector.score(job, row)
    decision = detector.decide(job, [row])

    assert score < settings.dedup_auto_merge_threshold
    assert decision.verdict is not DuplicateVerdict.DUPLICATE


def test_same_company_different_jobs_are_distinct() -> None:
    row = existing_row(
        title="product designer",
        description="craft beautiful mobile experiences and lead our design system work",
    )
    job = candidate()

    score = detector.score(job, row)
    decision = detector.decide(job, [row])

    assert score < settings.dedup_link_threshold
    assert decision.verdict is DuplicateVerdict.DISTINCT


def test_similar_descriptions_alone_are_not_enough() -> None:
    # Identical boilerplate description (plus location/date), completely
    # different role: the title gate must block any match — description is a
    # supporting signal and can never establish identity by itself.
    row = existing_row(title="product designer")
    job = candidate()

    title_sim = detector._identity.title_similarity(job.normalizedTitle, row.normalizedTitle)
    decision = detector.decide(job, [row])

    assert title_sim < settings.dedup_min_title_similarity  # gate applies
    assert decision.verdict is DuplicateVerdict.DISTINCT
    assert decision.matched_job_id is None


def test_false_positive_generic_title_different_team() -> None:
    row = existing_row(
        title="software engineer",
        location="pune, india",
        description="join the mobile apps team building our android and ios clients in kotlin and swift",
    )
    job = candidate(title="Software Engineer", location="Bengaluru, India")

    score = detector.score(job, row)
    decision = detector.decide(job, [row])

    assert decision.verdict is not DuplicateVerdict.DUPLICATE
    assert score < settings.dedup_auto_merge_threshold


def test_near_duplicate_band_links_without_merging() -> None:
    # Same title/company/location/date but no descriptions to confirm either
    # way: enough to relate, not enough to merge.
    row = existing_row(description=None)
    job = candidate(description=None)

    score = detector.score(job, row)
    decision = detector.decide(job, [row])

    assert settings.dedup_link_threshold <= score < settings.dedup_auto_merge_threshold
    assert decision.verdict is DuplicateVerdict.NEAR_DUPLICATE
    assert decision.matched_job_id == row.id


def test_best_match_picks_highest_scoring_candidate() -> None:
    weak = existing_row(title="product designer")
    strong = existing_row(title="backend engineer")
    job = candidate()

    decision = detector.decide(job, [weak, strong])

    assert decision.matched_job_id == strong.id


def test_no_candidates_is_distinct() -> None:
    decision = detector.decide(candidate(), [])
    assert decision.verdict is DuplicateVerdict.DISTINCT
    assert decision.matched_job_id is None
