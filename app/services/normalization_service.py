from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.schemas.search import SearchQuery
from app.sources.base import JobSourceConnector
from app.sources.models import NormalizedJob, RawJob
from app.utils.normalization import normalize_company, normalize_location

logger = get_logger(__name__)


class NormalizationService:
    """Validation + normalization stage of the pipeline, plus the post-filters
    connectors can't push down.

    Filter principle: exclude only on a DEFINITE mismatch. A job missing the
    filtered attribute is kept — sources routinely omit salary/experience/
    dates, and silently dropping those jobs would hide most real postings.
    Ranking (Phase 8) handles soft fit."""

    def normalize_batch(
        self, connector: JobSourceConnector, raws: list[RawJob]
    ) -> list[NormalizedJob]:
        normalized: list[NormalizedJob] = []
        for raw in raws:
            try:
                normalized.append(connector.normalize_job(raw))
            except Exception as exc:  # noqa: BLE001 - one bad payload must not sink the source
                logger.warning(
                    "job_normalize_skipped",
                    source=raw.sourceName,
                    external_id=raw.externalId,
                    error=str(exc),
                )
        return normalized

    def apply_filters(self, jobs: list[NormalizedJob], query: SearchQuery) -> list[NormalizedJob]:
        cutoff = (
            datetime.now(UTC) - timedelta(days=query.datePosted)
            if query.datePosted is not None
            else None
        )
        return [job for job in jobs if self._matches(job, query, cutoff)]

    def _matches(
        self, job: NormalizedJob, query: SearchQuery, cutoff: datetime | None
    ) -> bool:
        if query.remote is True and not (job.remote or job.hybrid):
            return False
        if query.remote is False and job.remote:
            return False

        if query.locations and not job.remote and job.normalizedLocation is not None:
            wanted = [normalize_location(loc) for loc in query.locations]
            if not any(w and w in job.normalizedLocation for w in wanted):
                return False

        if query.experience is not None:
            if (
                query.experience.max is not None
                and job.experienceMin is not None
                and job.experienceMin > query.experience.max
            ):
                return False
            if (
                query.experience.min is not None
                and job.experienceMax is not None
                and job.experienceMax < query.experience.min
            ):
                return False

        if (
            query.salary is not None
            and query.salary.min is not None
            and job.salaryMax is not None
            and (query.salary.currency is None or job.salaryCurrency in (None, query.salary.currency))
            and job.salaryMax < query.salary.min
        ):
            return False

        if cutoff is not None and job.postedAt is not None and job.postedAt < cutoff:
            return False

        if query.companies:
            company = normalize_company(job.companyName)
            wanted_companies = [normalize_company(c) for c in query.companies]
            if not any(w and (w in company or company in w) for w in wanted_companies):
                return False

        return True
