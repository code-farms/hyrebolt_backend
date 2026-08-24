from datetime import UTC, datetime, timedelta

from app.schemas.search import ExperienceFilter, SalaryFilter, SearchQuery
from app.services.normalization_service import NormalizationService
from app.sources import RawJob, SourceParseError, SourceSearchParams
from tests.discovery.fakes import StubConnector, make_normalized_job, make_stub_config

service = NormalizationService()
NOW = datetime.now(UTC)


class ExplodingConnector(StubConnector):
    def normalize_job(self, raw: RawJob):
        if raw.payload["i"] == 0:
            raise SourceParseError("alpha", "bad payload")
        return super().normalize_job(raw)


async def test_normalize_batch_skips_bad_payloads() -> None:
    jobs = [make_normalized_job(title="A"), make_normalized_job(title="B")]
    connector = ExplodingConnector("alpha", make_stub_config("alpha"), jobs=jobs)
    raws = await connector.search_jobs(SourceSearchParams())

    normalized = service.normalize_batch(connector, raws)

    assert len(normalized) == 1
    assert normalized[0].title == "B"


def test_salary_filter_null_semantics() -> None:
    query = SearchQuery(salary=SalaryFilter(min=100000, currency="USD"))
    unknown_salary = make_normalized_job(salary_max=None)
    too_low = make_normalized_job(salary_max=50000, salary_currency="USD")
    other_currency = make_normalized_job(salary_max=50000, salary_currency="INR")
    good = make_normalized_job(salary_max=150000, salary_currency="USD")

    kept = service.apply_filters([unknown_salary, too_low, other_currency, good], query)

    assert unknown_salary in kept  # missing data never excludes
    assert too_low not in kept  # definite mismatch
    assert other_currency in kept  # no FX guessing
    assert good in kept


def test_date_posted_filter_keeps_undated_jobs() -> None:
    query = SearchQuery(datePosted=7)
    fresh = make_normalized_job(posted_at=NOW - timedelta(days=2))
    stale = make_normalized_job(posted_at=NOW - timedelta(days=30))
    undated = make_normalized_job(posted_at=None)

    kept = service.apply_filters([fresh, stale, undated], query)

    assert fresh in kept and undated in kept and stale not in kept


def test_remote_and_location_filters() -> None:
    remote_query = SearchQuery(remote=True)
    onsite = make_normalized_job(remote=False, location="Pune")
    remote_job = make_normalized_job(remote=True)
    assert service.apply_filters([onsite, remote_job], remote_query) == [remote_job]

    location_query = SearchQuery(locations=["Bengaluru"])
    match = make_normalized_job(remote=False, location="Bengaluru, India")
    mismatch = make_normalized_job(remote=False, location="Pune, India")
    no_location = make_normalized_job(remote=False, location=None)
    remote_anyway = make_normalized_job(remote=True, location=None)
    kept = service.apply_filters([match, mismatch, no_location, remote_anyway], location_query)
    assert match in kept and no_location in kept and remote_anyway in kept
    assert mismatch not in kept


def test_experience_overlap_filter() -> None:
    query = SearchQuery(experience=ExperienceFilter(min=2, max=5))
    fits = make_normalized_job(experience_min=3, experience_max=6)
    too_senior = make_normalized_job(experience_min=8, experience_max=12)
    too_junior = make_normalized_job(experience_min=0, experience_max=1)
    unknown = make_normalized_job()

    kept = service.apply_filters([fits, too_senior, too_junior, unknown], query)

    assert fits in kept and unknown in kept
    assert too_senior not in kept and too_junior not in kept


def test_companies_filter_is_definite() -> None:
    query = SearchQuery(companies=["Acme"])
    match = make_normalized_job(company="Acme Robotics Inc.")
    other = make_normalized_job(company="Globex")

    kept = service.apply_filters([match, other], query)

    assert match in kept and other not in kept
