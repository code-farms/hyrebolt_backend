# Field names are camelCase on purpose: they mirror the Prisma Job/JobSource
# columns, so Phase 5 persistence is essentially model_dump().
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import EmploymentType


class SourceCapability(StrEnum):
    SEARCH = "search"
    DETAILS = "details"
    FEED = "feed"
    API = "api"
    STARTUP_METADATA = "startup_metadata"
    SCRAPE_PERMITTED_PAGES = "scrape_permitted_pages"


class JobSourceConfig(BaseModel):
    """Runtime configuration for one connector. Mirrors the JobSource DB row;
    the discovery engine merges operator state (enabled, rate limit) from the
    DB over these code defaults via registry.merge_config."""

    model_config = ConfigDict(frozen=True)

    name: str  # machine key, must match JobSource.name and the registry key
    displayName: str
    enabled: bool = False
    baseUrl: str | None = None
    rateLimitPerMinute: int | None = None
    requiresAuth: bool = False
    capabilities: tuple[SourceCapability, ...] = ()
    timeoutSeconds: float = 15.0
    # Connector-specific settings, e.g. company_careers board list or the
    # weworkremotely feed paths.
    extra: dict[str, Any] = Field(default_factory=dict)


class SourceSearchParams(BaseModel):
    """The subset of a Phase 5 SearchQuery a single connector can act on.
    Connectors MUST ignore (not error on) filters they cannot apply upstream;
    the pipeline re-filters after normalization."""

    model_config = ConfigDict(frozen=True)

    keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    remote: bool | None = None  # None = no constraint
    companies: tuple[str, ...] = ()
    postedSince: datetime | None = None
    limit: int = 50  # per-source cap


class RawJob(BaseModel):
    """Opaque source payload plus just enough envelope for details/dedup/audit."""

    sourceName: str
    externalId: str | None = None
    url: str | None = None
    payload: dict[str, Any]
    fetchedAt: datetime


class CompanyMetadata(BaseModel):
    """Startup/company metadata a connector legitimately knows about the
    employer (Phase 13). Every field is optional: unknown stays None, and the
    persistence layer only fills Company columns that are still null."""

    model_config = ConfigDict(frozen=True)

    website: str | None = None
    careersUrl: str | None = None
    industry: str | None = None
    stage: str | None = None
    location: str | None = None
    description: str | None = None
    logoUrl: str | None = None
    metadataSource: str | None = None  # e.g. "company_careers", "user"


class NormalizedJob(BaseModel):
    """Mirror of the creatable Prisma Job fields. Carries sourceName (not the
    DB sourceId): row resolution happens at persistence time. Absent data is
    None — connectors never fabricate values."""

    sourceName: str
    externalId: str | None = None
    sourceUrl: str | None = None
    canonicalUrl: str | None = None
    title: str
    normalizedTitle: str
    description: str | None = None
    companyName: str
    location: str | None = None
    normalizedLocation: str | None = None
    country: str | None = None
    remote: bool = False
    hybrid: bool = False
    employmentType: EmploymentType | None = None
    experienceMin: float | None = None
    experienceMax: float | None = None
    salaryMin: int | None = None
    salaryMax: int | None = None
    salaryCurrency: str | None = None
    postedAt: datetime | None = None
    rawData: dict[str, Any] | None = None
    contentHash: str
    company: CompanyMetadata | None = None


class SourceHealth(BaseModel):
    sourceName: str
    healthy: bool
    checkedAt: datetime
    latencyMs: float | None = None
    detail: str | None = None
