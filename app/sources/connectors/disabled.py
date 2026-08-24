from datetime import UTC, datetime

from app.sources.base import JobSourceConnector
from app.sources.exceptions import SourceDisabledError
from app.sources.models import NormalizedJob, RawJob, SourceHealth, SourceSearchParams


class DisabledConnector(JobSourceConnector):
    """Base for sources with no legitimate programmatic access path today.

    Per the project rules these ship as honest, documented stubs — never fake
    implementations and never scrapers that bypass auth, CAPTCHA, or anti-bot
    protection. Each subclass documents WHY it is disabled and what a legal
    path would look like (see docs/job-sources.md)."""

    #: Human-readable reason shown in errors and health checks.
    reason: str = "no legitimate programmatic access path"

    async def search_jobs(self, params: SourceSearchParams) -> list[RawJob]:
        raise SourceDisabledError(self.get_source_name(), self.reason)

    async def get_job_details(self, raw: RawJob) -> RawJob:
        raise SourceDisabledError(self.get_source_name(), self.reason)

    def normalize_job(self, raw: RawJob) -> NormalizedJob:
        raise SourceDisabledError(self.get_source_name(), self.reason)

    async def health_check(self) -> SourceHealth:
        return SourceHealth(
            sourceName=self.get_source_name(),
            healthy=False,
            checkedAt=datetime.now(UTC),
            detail=f"disabled: {self.reason}",
        )
