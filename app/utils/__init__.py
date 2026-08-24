"""Shared helpers that don't belong to a single service."""

from app.utils.normalization import (
    canonicalize_url,
    collapse_whitespace,
    compute_content_hash,
    map_employment_type,
    normalize_company,
    normalize_location,
    normalize_title,
    strip_html,
)

__all__ = [
    "canonicalize_url",
    "collapse_whitespace",
    "compute_content_hash",
    "map_employment_type",
    "normalize_company",
    "normalize_location",
    "normalize_title",
    "strip_html",
]
