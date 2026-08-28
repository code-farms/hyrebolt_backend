import pytest

from app.utils.normalization import normalize_title
from app.utils.role_family import (
    _ROLE_PATTERNS,
    OTHER_ROLE_FAMILY,
    ROLE_FAMILIES,
    classify_role,
    role_family_label,
)


@pytest.mark.parametrize(
    ("title", "family"),
    [
        # Backend / frontend / full stack, including precedence.
        ("Senior Backend Engineer (Python/Django)", "backend"),
        ("Java Developer", "backend"),
        ("Node.js Engineer", "backend"),
        ("Go Engineer", "backend"),
        ("Ruby on Rails Developer", "backend"),
        ("React Developer", "frontend"),
        ("Frontend Engineer - Angular", "frontend"),
        ("UI Engineer", "frontend"),
        ("Full Stack Developer (React + Node)", "full_stack"),
        ("Fullstack Engineer", "full_stack"),
        # Data vs ML: "data scientist" is ML, "data engineer python" is data.
        ("Data Engineer (Python, Spark)", "data"),
        ("Business Intelligence Analyst", "data"),
        ("Data Scientist", "ml_ai"),
        ("Machine Learning Engineer", "ml_ai"),
        ("Generative AI Engineer", "ml_ai"),
        # Infra / mobile / QA / security.
        ("DevOps Engineer", "devops_sre"),
        ("Site Reliability Engineer", "devops_sre"),
        ("Platform Engineer", "devops_sre"),
        ("iOS Developer", "mobile"),
        ("React Native Developer", "mobile"),
        ("Android Engineer (Kotlin)", "mobile"),
        ("QA Automation Engineer", "qa"),
        ("SDET", "qa"),
        ("Application Security Engineer", "security"),
        # Product / design and the catch-alls.
        ("Product Designer", "product_design"),
        ("UI/UX Designer", "product_design"),
        ("Senior Product Manager", "product_design"),
        ("Software Engineer II", "software_general"),
        ("Software Development Engineer", "software_general"),
        ("Account Executive", OTHER_ROLE_FAMILY),
        ("Chicago Sales Lead", OTHER_ROLE_FAMILY),  # "go" inside a word must not match
        ("", OTHER_ROLE_FAMILY),
    ],
)
def test_classify_role(title: str, family: str) -> None:
    assert classify_role(normalize_title(title)) == family


def test_every_pattern_maps_to_a_known_family() -> None:
    assert {family for _, family in _ROLE_PATTERNS} <= set(ROLE_FAMILIES)
    assert OTHER_ROLE_FAMILY in ROLE_FAMILIES


def test_role_family_label_falls_back_to_other() -> None:
    assert role_family_label("backend") == "Backend"
    assert role_family_label("nonsense") == ROLE_FAMILIES[OTHER_ROLE_FAMILY]
