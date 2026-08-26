# camelCase wire contract, mirrored by the frontend zod schemas (Phase 13).
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.db.generated.models import Company, CompanyWatchlist
from app.models import WatchlistPriority

METADATA_SOURCE_USER = "user"


def _clean_roles(roles: list[str]) -> list[str]:
    cleaned = [role.strip() for role in roles if role and role.strip()]
    return list(dict.fromkeys(cleaned))


def _clean_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("must be an http(s) URL")
    return value


class WatchlistSummaryOut(BaseModel):
    id: str
    priority: WatchlistPriority


class CompanyOut(BaseModel):
    id: str
    name: str
    website: str | None
    careersUrl: str | None
    industry: str | None
    stage: str | None
    location: str | None
    description: str | None
    logoUrl: str | None
    metadataSource: str | None
    openPositions: int
    # The viewer's watchlist entry, if any.
    watchlist: WatchlistSummaryOut | None
    createdAt: datetime


class CompanyListOut(BaseModel):
    items: list[CompanyOut]
    total: int
    limit: int
    offset: int


class WatchlistEntryOut(BaseModel):
    id: str
    company: CompanyOut
    priority: WatchlistPriority
    preferredRoles: list[str]
    excludedRoles: list[str]
    notes: str | None
    createdAt: datetime
    updatedAt: datetime


class WatchlistListOut(BaseModel):
    items: list[WatchlistEntryOut]
    total: int


class WatchlistCreateIn(BaseModel):
    """Watch an existing company (companyId) or one by name — the latter
    creates the Company row so a startup can be watched before any of its
    jobs have been discovered."""

    companyId: str | None = None
    companyName: str | None = Field(default=None, min_length=1, max_length=200)
    priority: WatchlistPriority = WatchlistPriority.MEDIUM
    preferredRoles: list[str] = Field(default_factory=list, max_length=20)
    excludedRoles: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    careersUrl: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=500)

    @field_validator("preferredRoles", "excludedRoles")
    @classmethod
    def clean_roles(cls, value: list[str]) -> list[str]:
        return _clean_roles(value)

    @field_validator("careersUrl", "website")
    @classmethod
    def clean_url(cls, value: str | None) -> str | None:
        return _clean_url(value)

    @model_validator(mode="after")
    def require_company(self) -> "WatchlistCreateIn":
        if bool(self.companyId) == bool(self.companyName and self.companyName.strip()):
            raise ValueError("Provide exactly one of companyId or companyName.")
        return self


class WatchlistUpdateIn(BaseModel):
    priority: WatchlistPriority | None = None
    preferredRoles: list[str] | None = Field(default=None, max_length=20)
    excludedRoles: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("preferredRoles", "excludedRoles")
    @classmethod
    def clean_roles(cls, value: list[str] | None) -> list[str] | None:
        return _clean_roles(value) if value is not None else None

    def to_update(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class CompanyMetadataIn(BaseModel):
    """User-supplied startup metadata. Anything left unset stays as it is;
    an explicit null clears the field. Never inferred."""

    website: str | None = Field(default=None, max_length=500)
    careersUrl: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=120)
    stage: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("website", "careersUrl")
    @classmethod
    def clean_url(cls, value: str | None) -> str | None:
        return _clean_url(value)

    @field_validator("industry", "stage", "location", "description")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    def to_update(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


def company_out(
    company: Company,
    *,
    open_positions: int,
    entry: CompanyWatchlist | None = None,
) -> CompanyOut:
    if entry is None:
        viewer_entries = getattr(company, "watchlistEntries", None) or []
        entry = viewer_entries[0] if viewer_entries else None
    return CompanyOut(
        id=company.id,
        name=company.name,
        website=company.website,
        careersUrl=company.careersUrl,
        industry=company.industry,
        stage=company.stage,
        location=company.location,
        description=company.description,
        logoUrl=company.logoUrl,
        metadataSource=company.metadataSource,
        openPositions=open_positions,
        watchlist=WatchlistSummaryOut(id=entry.id, priority=entry.priority) if entry else None,
        createdAt=company.createdAt,
    )


def watchlist_entry_out(entry: CompanyWatchlist, *, open_positions: int) -> WatchlistEntryOut:
    assert entry.company is not None
    return WatchlistEntryOut(
        id=entry.id,
        company=company_out(entry.company, open_positions=open_positions, entry=entry),
        priority=entry.priority,
        preferredRoles=list(entry.preferredRoles),
        excludedRoles=list(entry.excludedRoles),
        notes=entry.notes,
        createdAt=entry.createdAt,
        updatedAt=entry.updatedAt,
    )
