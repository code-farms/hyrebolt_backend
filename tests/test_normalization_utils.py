from app.models import EmploymentType
from app.utils.normalization import (
    canonicalize_url,
    compute_content_hash,
    map_employment_type,
    normalize_company,
    normalize_location,
    normalize_title,
    strip_html,
)


def test_normalize_title_strips_punctuation_case_and_whitespace() -> None:
    assert normalize_title("  Sr. Backend Engineer (Python/Django)! ") == (
        "sr backend engineer python django"
    )
    assert normalize_title("Führungskraft – Café") == normalize_title("führungskraft café")


def test_normalize_location() -> None:
    assert normalize_location("  Bengaluru,   India ") == "bengaluru, india"
    assert normalize_location("") is None
    assert normalize_location(None) is None


def test_normalize_company_strips_legal_suffixes() -> None:
    assert normalize_company("Acme Robotics Inc.") == "acme robotics"
    assert normalize_company("Globex Pvt. Ltd.") == normalize_company("globex pvt")
    assert normalize_company("Initech") == "initech"


def test_strip_html() -> None:
    assert strip_html("<p>Build <strong>APIs</strong> &amp; tools.</p>") == "Build APIs & tools."


def test_canonicalize_url_drops_tracking_and_fragments() -> None:
    assert canonicalize_url(
        "HTTPS://Remoteok.com/remote-jobs/1001/?utm_source=feed&ref=x&id=2#apply"
    ) == "https://remoteok.com/remote-jobs/1001?id=2"
    assert canonicalize_url(None) is None
    assert canonicalize_url("") is None


def test_map_employment_type() -> None:
    assert map_employment_type("Full-time") is EmploymentType.FULL_TIME
    assert map_employment_type("part time") is EmploymentType.PART_TIME
    assert map_employment_type("Internship") is EmploymentType.INTERNSHIP
    assert map_employment_type("some weird thing") is None
    assert map_employment_type(None) is None


def test_content_hash_is_deterministic_and_normalization_insensitive() -> None:
    first = compute_content_hash(
        normalized_title="backend engineer",
        company_name="Acme Robotics Inc.",
        normalized_location="remote",
        description="<p>Build APIs</p>",
    )
    second = compute_content_hash(
        normalized_title="backend engineer",
        company_name="acme robotics",  # suffix + case differences must not matter
        normalized_location="remote",
        description="Build   APIs",  # markup/whitespace differences must not matter
    )
    assert first == second
    assert len(first) == 64  # sha256 hex

    different = compute_content_hash(
        normalized_title="frontend engineer",
        company_name="Acme Robotics Inc.",
        normalized_location="remote",
        description="<p>Build APIs</p>",
    )
    assert different != first
