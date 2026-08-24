"""We Work Remotely — public category RSS feeds.

WWR publishes its listings as RSS for exactly this kind of consumption. Feed
paths are configuration (config.extra["feeds"]), defaulting to the
programming category. All postings are remote by definition.
"""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

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

DEFAULT_FEEDS = ["/categories/remote-programming-jobs.rss"]


class WeWorkRemotelyConnector(JobSourceConnector):
    async def search_jobs(self, params: SourceSearchParams) -> list[RawJob]:
        if params.remote is False:
            return []

        feeds: list[str] = list(self._config.extra.get("feeds", DEFAULT_FEEDS))
        fetched_at = datetime.now(UTC)
        raw_jobs: list[RawJob] = []
        for feed_path in feeds:
            xml_text = await self._http.get_text(f"{self._config.baseUrl}{feed_path}")
            for item in self._parse_feed(xml_text):
                if not self._matches(item, params):
                    continue
                raw_jobs.append(
                    RawJob(
                        sourceName=self.get_source_name(),
                        externalId=item.get("guid") or item.get("link"),
                        url=item.get("link"),
                        payload=item,
                        fetchedAt=fetched_at,
                    )
                )
                if len(raw_jobs) >= params.limit:
                    return raw_jobs
        return raw_jobs

    def normalize_job(self, raw: RawJob) -> NormalizedJob:
        item = raw.payload
        raw_title = str(item.get("title") or "")
        company, _, title = raw_title.partition(": ")
        if not title:
            # No "Company: Role" separator — treat the whole string as title.
            company, title = "", raw_title
        title = title.strip()
        company = company.strip()
        if not title or not company:
            raise SourceParseError(self.get_source_name(), f"unparseable item title: {raw_title!r}")

        description_html = item.get("description")
        description = strip_html(description_html) if description_html else None
        location = str(item["region"]).strip() or None if item.get("region") else None
        normalized_title = normalize_title(title)
        normalized_location = normalize_location(location)

        return NormalizedJob(
            sourceName=self.get_source_name(),
            externalId=item.get("guid") or item.get("link"),
            sourceUrl=item.get("link"),
            canonicalUrl=canonicalize_url(item.get("link")),
            title=title,
            normalizedTitle=normalized_title,
            description=description,
            companyName=company,
            location=location,
            normalizedLocation=normalized_location,
            remote=True,
            postedAt=_parse_pub_date(item.get("pubDate")),
            rawData=item,
            contentHash=compute_content_hash(
                normalized_title=normalized_title,
                company_name=company,
                normalized_location=normalized_location,
                description=description,
            ),
        )

    def _parse_feed(self, xml_text: str) -> list[dict[str, str]]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise SourceParseError(self.get_source_name(), "invalid RSS XML") from exc
        items: list[dict[str, str]] = []
        for element in root.iter("item"):
            item: dict[str, str] = {}
            for child in element:
                tag = child.tag.rsplit("}", 1)[-1]  # strip any namespace
                if child.text and child.text.strip():
                    item[tag] = child.text.strip()
            items.append(item)
        return items

    def _matches(self, item: dict[str, str], params: SourceSearchParams) -> bool:
        if params.postedSince is not None:
            posted_at = _parse_pub_date(item.get("pubDate"))
            if posted_at is None or posted_at < params.postedSince:
                return False
        if params.keywords:
            haystack = " ".join([item.get("title", ""), item.get("category", "")]).casefold()
            if not any(keyword.casefold() in haystack for keyword in params.keywords):
                return False
        return True


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
