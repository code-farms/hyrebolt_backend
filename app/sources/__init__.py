"""Pluggable job-source system. Connectors implement JobSourceConnector; the
registry builds them from code-default configs (optionally merged with the
JobSource DB rows by the discovery engine). See docs/job-sources.md."""

from app.sources.base import JobSourceConnector
from app.sources.exceptions import (
    SourceAuthRequiredError,
    SourceDisabledError,
    SourceError,
    SourceNotFoundError,
    SourceParseError,
    SourceRateLimitedError,
    SourceUnavailableError,
)
from app.sources.models import (
    JobSourceConfig,
    NormalizedJob,
    RawJob,
    SourceCapability,
    SourceHealth,
    SourceSearchParams,
)
from app.sources.registry import DEFAULT_CONFIGS, SourceRegistry, merge_config

__all__ = [
    "DEFAULT_CONFIGS",
    "JobSourceConfig",
    "JobSourceConnector",
    "NormalizedJob",
    "RawJob",
    "SourceAuthRequiredError",
    "SourceCapability",
    "SourceDisabledError",
    "SourceError",
    "SourceHealth",
    "SourceNotFoundError",
    "SourceParseError",
    "SourceRateLimitedError",
    "SourceRegistry",
    "SourceSearchParams",
    "SourceUnavailableError",
    "merge_config",
]
