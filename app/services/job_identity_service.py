"""Identity signals for deduplication (Phase 6).

Pure, deterministic similarity primitives over normalized job fields. The
weighting/threshold policy lives in DuplicateDetectionService; this module
only answers "how alike are these two values?" — returning None when a signal
is unavailable so the scorer can renormalize instead of guessing."""

from datetime import datetime
from difflib import SequenceMatcher


class JobIdentityService:
    @staticmethod
    def title_similarity(a: str, b: str) -> float:
        """Max of token-set Jaccard and character-sequence ratio: Jaccard
        handles word reordering, the ratio handles abbreviation variants
        ("sr" vs "senior")."""
        if a == b:
            return 1.0
        tokens_a, tokens_b = set(a.split()), set(b.split())
        jaccard = 0.0
        if tokens_a and tokens_b:
            jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        ratio = SequenceMatcher(None, a, b).ratio()
        return max(jaccard, ratio)

    @staticmethod
    def location_similarity(a: str | None, b: str | None) -> float | None:
        """None when either side is unknown (signal unavailable). Containment
        counts as a match: "bengaluru" vs "bengaluru, india"."""
        if not a or not b:
            return None
        if a == b or a in b or b in a:
            return 1.0
        return 0.0

    @staticmethod
    def description_similarity(a: str | None, b: str | None) -> float | None:
        """Jaccard over 3-token shingles of the (already normalized) text.
        A supporting signal only — boilerplate makes descriptions look alike,
        so the weights never let it establish identity by itself."""
        if not a or not b:
            return None
        shingles_a = JobIdentityService._shingles(a.casefold())
        shingles_b = JobIdentityService._shingles(b.casefold())
        if not shingles_a or not shingles_b:
            return None
        return len(shingles_a & shingles_b) / len(shingles_a | shingles_b)

    @staticmethod
    def posted_date_proximity(a: datetime | None, b: datetime | None) -> float | None:
        if a is None or b is None:
            return None
        delta_days = abs((a - b).total_seconds()) / 86400
        if delta_days <= 7:
            return 1.0
        if delta_days <= 30:
            return 0.5
        return 0.0

    @staticmethod
    def _shingles(text: str, size: int = 3, max_tokens: int = 300) -> set[tuple[str, ...]]:
        tokens = text.split()[:max_tokens]
        if len(tokens) < size:
            return {tuple(tokens)} if tokens else set()
        return {tuple(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}
