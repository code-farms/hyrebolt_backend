from datetime import UTC, datetime, timedelta

from app.services.job_identity_service import JobIdentityService

identity = JobIdentityService()


def test_title_similarity_exact_and_variants() -> None:
    assert identity.title_similarity("backend engineer", "backend engineer") == 1.0
    variant = identity.title_similarity("senior backend engineer", "sr backend engineer")
    assert variant > 0.8  # abbreviation variant still reads as the same role
    different = identity.title_similarity("backend engineer", "product designer")
    assert different < 0.5


def test_title_similarity_handles_reordering() -> None:
    assert identity.title_similarity("engineer backend", "backend engineer") >= 0.9


def test_location_similarity_none_when_unknown() -> None:
    assert identity.location_similarity(None, "bengaluru") is None
    assert identity.location_similarity("bengaluru", None) is None
    assert identity.location_similarity("bengaluru", "bengaluru, india") == 1.0
    assert identity.location_similarity("pune", "bengaluru") == 0.0


def test_description_similarity() -> None:
    text = "we build payment infrastructure for merchants across india at scale"
    assert identity.description_similarity(text, text) == 1.0
    assert identity.description_similarity(text, None) is None
    other = "join our design team to craft beautiful mobile experiences for users"
    similarity = identity.description_similarity(text, other)
    assert similarity is not None and similarity < 0.1


def test_posted_date_proximity_buckets() -> None:
    base = datetime(2026, 8, 20, tzinfo=UTC)
    assert identity.posted_date_proximity(base, base + timedelta(days=3)) == 1.0
    assert identity.posted_date_proximity(base, base + timedelta(days=20)) == 0.5
    assert identity.posted_date_proximity(base, base + timedelta(days=90)) == 0.0
    assert identity.posted_date_proximity(base, None) is None
