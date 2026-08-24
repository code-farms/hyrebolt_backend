"""Remote OK — official public JSON API (https://remoteok.com/api).

The API's own legal notice requires linking back to the job's Remote OK URL
and crediting the source when displaying the data; the stored sourceUrl serves
exactly that. All jobs on this source are remote by definition.
"""

from datetime import UTC, datetime
from typing import Any

from app.sources.base import JobSourceConnector
from app.sources.exceptions import SourceParseError
from app.sources.models import NormalizedJob, RawJob, SourceSearchParams
from app.utils.normalization import (
    canonicalize_url,
    compute_content_hash,
    normalize_location,
    normalize_title,
    strip_html,
)


class RemoteOkConnector(JobSourceConnector):
    async def search_jobs(self, params: SourceSearchParams) -> list[RawJob]:
        if params.remote is False:
            return []  # every posting here is remote

        payload = await self._http.get_json(f"{self._config.baseUrl}/api")
        if not isinstance(payload, list):
            raise SourceParseError(self.get_source_name(), "expected a JSON array")

        fetched_at = datetime.now(UTC)
        raw_jobs: list[RawJob] = []
        for item in payload:
            # The first element is a legal notice, not a job.
            if not isinstance(item, dict) or "id" not in item:
                continue
            if not self._matches(item, params):
                continue
            raw_jobs.append(
                RawJob(
                    sourceName=self.get_source_name(),
                    externalId=str(item["id"]),
                    url=item.get("url"),
                    payload=item,
                    fetchedAt=fetched_at,
                )
            )
            if len(raw_jobs) >= params.limit:
                break
        return raw_jobs

    def normalize_job(self, raw: RawJob) -> NormalizedJob:
        item = raw.payload
        title = str(item.get("position") or "").strip()
        company = str(item.get("company") or "").strip()
        if not title or not company:
            raise SourceParseError(self.get_source_name(), "item missing position/company")

        description_html = item.get("description")
        description = strip_html(description_html) if description_html else None
        location = str(item["location"]).strip() or None if item.get("location") else None
        normalized_title = normalize_title(title)
        normalized_location = normalize_location(location)
        posted_at = _parse_date(item.get("date"))
        salary_min = _positive_int(item.get("salary_min"))
        salary_max = _positive_int(item.get("salary_max"))

        return NormalizedJob(
            sourceName=self.get_source_name(),
            externalId=str(item["id"]),
            sourceUrl=item.get("url"),
            canonicalUrl=canonicalize_url(item.get("url")),
            title=title,
            normalizedTitle=normalized_title,
            description=description,
            companyName=company,
            location=location,
            normalizedLocation=normalized_location,
            remote=True,
            salaryMin=salary_min,
            salaryMax=salary_max,
            # The API documents salary figures as USD/year.
            salaryCurrency="USD" if salary_min or salary_max else None,
            postedAt=posted_at,
            rawData=item,
            contentHash=compute_content_hash(
                normalized_title=normalized_title,
                company_name=company,
                normalized_location=normalized_location,
                description=description,
            ),
        )

    def _matches(self, item: dict[str, Any], params: SourceSearchParams) -> bool:
        if params.postedSince is not None:
            posted_at = _parse_date(item.get("date"))
            if posted_at is None or posted_at < params.postedSince:
                return False
        if params.keywords:
            haystack = " ".join(
                [
                    str(item.get("position") or ""),
                    str(item.get("company") or ""),
                    " ".join(str(tag) for tag in item.get("tags") or []),
                ]
            ).casefold()
            if not any(keyword.casefold() in haystack for keyword in params.keywords):
                return False
        return True


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _positive_int(value: object) -> int | None:
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None
