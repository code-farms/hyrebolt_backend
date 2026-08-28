"""Role-family classification for analytics (Phase 17).

Jobs carry no role/category column, so "Backend / Frontend / Data …" is derived
from ``Job.normalizedTitle`` (already casefolded and punctuation-stripped by
``normalize_title``). Pure and deterministic, like the rest of ``app.utils``:
the database groups by title, the service folds titles into these families.
"""

import re

OTHER_ROLE_FAMILY = "other"

# Stable wire keys -> human labels. Order here is the display fallback order.
ROLE_FAMILIES: dict[str, str] = {
    "full_stack": "Full Stack",
    "backend": "Backend",
    "frontend": "Frontend",
    "mobile": "Mobile",
    "data": "Data",
    "ml_ai": "ML / AI",
    "devops_sre": "DevOps / SRE",
    "qa": "QA / Test",
    "security": "Security",
    "product_design": "Product / Design",
    "software_general": "Software (general)",
    OTHER_ROLE_FAMILY: "Other",
}

# First match wins, so the more specific families come first: "full stack
# react node" is full-stack, "data engineer python" is data, "react native
# developer" is mobile. Generic "software engineer" falls through to the
# catch-all software family; anything else (sales, HR, …) is "other".
_ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"full\s?stack"), "full_stack"),
    (
        re.compile(
            r"machine learning|\bml\b|\bai\b|deep learning|\bllm|\bnlp\b|computer vision"
            r"|data scien|\bgenai\b|generative"
        ),
        "ml_ai",
    ),
    (re.compile(r"\bdata\b|analytics|\betl\b|\bbi\b|warehouse|analyst"), "data"),
    (
        re.compile(
            r"devops|\bsre\b|site reliability|platform engineer|infrastructure|cloud engineer"
            r"|cloud architect|release engineer"
        ),
        "devops_sre",
    ),
    (re.compile(r"android|\bios\b|mobile|flutter|react native"), "mobile"),
    (re.compile(r"\bqa\b|quality|test engineer|\bsdet\b|automation engineer|tester"), "qa"),
    (re.compile(r"security|appsec|\bsoc\b|penetration"), "security"),
    (
        re.compile(
            r"front\s?end|\breact\b|angular|\bvue\b|\bui engineer|web developer"
            r"|javascript developer|typescript developer"
        ),
        "frontend",
    ),
    (
        re.compile(
            r"back\s?end|python|\bjava\b|golang|\bgo\b|node|django|spring|\bapi\b|\bnet\b"
            r"|rails|ruby|\bphp\b|scala|server|\bc\b|c\+\+|rust|elixir"
        ),
        "backend",
    ),
    (re.compile(r"product manager|product owner|designer|\bux\b"), "product_design"),
    (re.compile(r"software|developer|engineer|\bsde\b|programmer"), "software_general"),
]


def classify_role(normalized_title: str) -> str:
    """Map a normalized job title to a ``ROLE_FAMILIES`` key."""
    text = normalized_title.strip()
    if not text:
        return OTHER_ROLE_FAMILY
    for pattern, family in _ROLE_PATTERNS:
        if pattern.search(text):
            return family
    return OTHER_ROLE_FAMILY


def role_family_label(family: str) -> str:
    return ROLE_FAMILIES.get(family, ROLE_FAMILIES[OTHER_ROLE_FAMILY])
