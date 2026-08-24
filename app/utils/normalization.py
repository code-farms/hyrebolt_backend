"""Text/URL normalization shared by the source connectors (Phase 4), the
normalization service (Phase 5), and the dedup engine (Phase 6). Everything
here is pure and deterministic: no clocks, no locale, no network."""

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models import EmploymentType

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:inc|incorporated|ltd|limited|llc|llp|pvt|private|corp|corporation|co|gmbh)\.?$"
)
# Tracking params that never identify a job posting.
_TRACKING_PARAM_RE = re.compile(r"^(?:utm_\w+|ref|source|gh_src|lever-source)$", re.IGNORECASE)

_EMPLOYMENT_TYPE_PATTERNS: list[tuple[re.Pattern[str], EmploymentType]] = [
    (re.compile(r"full[\s_-]?time"), EmploymentType.FULL_TIME),
    (re.compile(r"part[\s_-]?time"), EmploymentType.PART_TIME),
    (re.compile(r"intern(?:ship)?"), EmploymentType.INTERNSHIP),
    (re.compile(r"contract(?:or)?"), EmploymentType.CONTRACT),
    (re.compile(r"freelance"), EmploymentType.FREELANCE),
    (re.compile(r"temp(?:orary)?"), EmploymentType.TEMPORARY),
]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(value: str) -> str:
    """Drop tags, unescape entities, collapse whitespace."""
    parser = _TextExtractor()
    parser.feed(html.unescape(value))
    return collapse_whitespace(" ".join(parser.parts))


def collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    text = _PUNCTUATION_RE.sub(" ", text)
    return collapse_whitespace(text)


def normalize_location(location: str | None) -> str | None:
    if location is None:
        return None
    text = collapse_whitespace(unicodedata.normalize("NFKC", location).casefold())
    return text or None


def normalize_company(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = collapse_whitespace(text)
    # Strip stacked legal suffixes ("pvt ltd", "inc llc") until stable, but
    # never reduce the name to nothing.
    while True:
        stripped = collapse_whitespace(_COMPANY_SUFFIX_RE.sub("", text))
        if stripped == text or not stripped:
            return text if not stripped else stripped
        text = stripped


def _normalize_description(description: str | None) -> str:
    if description is None:
        return ""
    return collapse_whitespace(
        unicodedata.normalize("NFKC", strip_html(description)).casefold()
    )


def compute_content_hash(
    *,
    normalized_title: str,
    company_name: str,
    normalized_location: str | None,
    description: str | None,
) -> str:
    """The Job.contentHash recipe: sha256 over normalized
    title|company|location|description. Inputs `normalized_title` and
    `normalized_location` are expected to already be normalized (they are the
    values stored on the Job row), so a hash recomputed from a stored row
    matches the one computed at discovery time."""
    parts = (
        normalized_title,
        normalize_company(company_name),
        normalized_location or "",
        _normalize_description(description),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def canonicalize_url(url: str | None) -> str | None:
    """Stable form for dedup signal 1: lowercase scheme/host, drop fragments,
    tracking params, and trailing slashes."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip() or None
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAM_RE.match(key)
    ]
    path = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def map_employment_type(value: str | None) -> EmploymentType | None:
    """Best-effort mapping of free-text employment types. Unknown → None,
    never a guess."""
    if not value:
        return None
    text = value.casefold()
    for pattern, employment_type in _EMPLOYMENT_TYPE_PATTERNS:
        if pattern.search(text):
            return employment_type
    return None
