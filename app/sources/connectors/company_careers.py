"""Company career pages — via Greenhouse and Lever public board APIs.

Both providers expose read-only JSON endpoints that exist specifically so
third parties can render a company's public job board:
- Greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
- Lever:      https://api.lever.co/v0/postings/{token}?mode=json

The watched companies are configuration, not code:
config.extra["boards"] = [{"company": "...", "provider": "greenhouse"|"lever",
"token": "..."}]. Empty by default. A single failing board is logged and
skipped; the connector only errors if every board fails.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.sources.base import JobSourceConnector
from app.sources.boards import public_board_url
from app.sources.exceptions import SourceError, SourceParseError, SourceUnavailableError
from app.sources.models import CompanyMetadata, NormalizedJob, RawJob, SourceSearchParams
from app.utils.normalization import (
    canonicalize_url,
    compute_content_hash,
    map_employment_type,
    normalize_location,
    normalize_title,
    strip_html,
)

logger = get_logger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
LEVER_API = "https://api.lever.co/v0/postings"


class CompanyCareersConnector(JobSourceConnector):
    async def search_jobs(self, params: SourceSearchParams) -> list[RawJob]:
        boards: list[dict[str, str]] = list(self._config.extra.get("boards", []))
        if params.companies:
            wanted = {company.casefold() for company in params.companies}
            boards = [board for board in boards if board["company"].casefold() in wanted]
        if not boards:
            return []

        fetched_at = datetime.now(UTC)
        raw_jobs: list[RawJob] = []
        failures: list[str] = []
        for board in boards:
            try:
                board_jobs = await self._fetch_board(board, fetched_at)
            except SourceError as exc:
                failures.append(f"{board['company']}: {exc.message}")
                logger.warning(
                    "career_board_failed", company=board["company"], detail=exc.message
                )
                continue
            for raw in board_jobs:
                if not self._matches(raw.payload, params):
                    continue
                raw_jobs.append(raw)
                if len(raw_jobs) >= params.limit:
                    return raw_jobs
        if failures and not raw_jobs and len(failures) == len(boards):
            raise SourceUnavailableError(
                self.get_source_name(), f"all boards failed: {'; '.join(failures)}"
            )
        return raw_jobs

    def normalize_job(self, raw: RawJob) -> NormalizedJob:
        provider = raw.payload.get("provider")
        if provider == "greenhouse":
            return self._normalize_greenhouse(raw)
        if provider == "lever":
            return self._normalize_lever(raw)
        raise SourceParseError(self.get_source_name(), f"unknown provider: {provider!r}")

    async def _fetch_board(self, board: dict[str, str], fetched_at: datetime) -> list[RawJob]:
        provider, token, company = board["provider"], board["token"], board["company"]
        if provider == "greenhouse":
            data = await self._http.get_json(
                f"{GREENHOUSE_API}/{token}/jobs", params={"content": "true"}
            )
            jobs = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(jobs, list):
                raise SourceParseError(self.get_source_name(), f"unexpected Greenhouse shape for {token}")
        elif provider == "lever":
            jobs = await self._http.get_json(f"{LEVER_API}/{token}", params={"mode": "json"})
            if not isinstance(jobs, list):
                raise SourceParseError(self.get_source_name(), f"unexpected Lever shape for {token}")
        else:
            raise SourceParseError(self.get_source_name(), f"unknown provider: {provider!r}")

        return [
            RawJob(
                sourceName=self.get_source_name(),
                externalId=f"{provider}:{token}:{job.get('id')}",
                url=job.get("absolute_url") or job.get("hostedUrl"),
                payload={
                    "provider": provider,
                    "company": company,
                    "token": token,
                    "website": board.get("website"),
                    "job": job,
                },
                fetchedAt=fetched_at,
            )
            for job in jobs
            if isinstance(job, dict)
        ]

    def _company_metadata(self, raw: RawJob) -> CompanyMetadata:
        """Phase 13: the only startup metadata a board legitimately tells us is
        its own public URL (plus an operator-supplied website). Nothing else
        is inferred."""
        provider = str(raw.payload.get("provider") or "")
        token = raw.payload.get("token")
        website = raw.payload.get("website")
        return CompanyMetadata(
            careersUrl=public_board_url(provider, str(token)) if token else None,
            website=str(website) if website else None,
            metadataSource=self.get_source_name(),
        )

    def _matches(self, payload: dict[str, Any], params: SourceSearchParams) -> bool:
        if not params.keywords:
            return True
        job = payload.get("job", {})
        haystack = str(job.get("title") or job.get("text") or "").casefold()
        return any(keyword.casefold() in haystack for keyword in params.keywords)

    def _normalize_greenhouse(self, raw: RawJob) -> NormalizedJob:
        job = raw.payload["job"]
        company = str(raw.payload.get("company") or "").strip()
        title = str(job.get("title") or "").strip()
        if not title or not company:
            raise SourceParseError(self.get_source_name(), "greenhouse job missing title/company")

        location_obj = job.get("location") or {}
        location = str(location_obj.get("name") or "").strip() or None
        content = job.get("content")
        description = strip_html(content) if content else None
        normalized_title = normalize_title(title)
        normalized_location = normalize_location(location)
        url = job.get("absolute_url")

        return NormalizedJob(
            sourceName=self.get_source_name(),
            externalId=raw.externalId,
            sourceUrl=url,
            canonicalUrl=canonicalize_url(url),
            title=title,
            normalizedTitle=normalized_title,
            description=description,
            companyName=company,
            location=location,
            normalizedLocation=normalized_location,
            remote="remote" in (normalized_location or ""),
            postedAt=_parse_iso(job.get("updated_at") or job.get("first_published")),
            rawData=raw.payload,
            contentHash=compute_content_hash(
                normalized_title=normalized_title,
                company_name=company,
                normalized_location=normalized_location,
                description=description,
            ),
            company=self._company_metadata(raw),
        )

    def _normalize_lever(self, raw: RawJob) -> NormalizedJob:
        job = raw.payload["job"]
        company = str(raw.payload.get("company") or "").strip()
        title = str(job.get("text") or "").strip()
        if not title or not company:
            raise SourceParseError(self.get_source_name(), "lever posting missing text/company")

        categories = job.get("categories") or {}
        location = str(categories.get("location") or "").strip() or None
        description = (
            str(job["descriptionPlain"]).strip()
            if job.get("descriptionPlain")
            else (strip_html(job["description"]) if job.get("description") else None)
        )
        workplace = str(job.get("workplaceType") or "").casefold()
        normalized_title = normalize_title(title)
        normalized_location = normalize_location(location)
        url = job.get("hostedUrl")

        return NormalizedJob(
            sourceName=self.get_source_name(),
            externalId=raw.externalId,
            sourceUrl=url,
            canonicalUrl=canonicalize_url(url),
            title=title,
            normalizedTitle=normalized_title,
            description=description,
            companyName=company,
            location=location,
            normalizedLocation=normalized_location,
            country=str(job["country"]).strip() or None if job.get("country") else None,
            remote=workplace == "remote",
            hybrid=workplace == "hybrid",
            employmentType=map_employment_type(categories.get("commitment")),
            postedAt=_parse_epoch_ms(job.get("createdAt")),
            rawData=raw.payload,
            contentHash=compute_content_hash(
                normalized_title=normalized_title,
                company_name=company,
                normalized_location=normalized_location,
                description=description,
            ),
            company=self._company_metadata(raw),
        )


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_epoch_ms(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
