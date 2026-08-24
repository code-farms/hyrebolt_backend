from app.services.deduplication_service import DeduplicationService
from tests.discovery.fakes import (
    FakeCompanyRepository,
    FakeJobRepository,
    FakeJobSourceRepository,
    FakeListingRepository,
    FakeSourceRow,
    make_normalized_job,
)

ALPHA = FakeSourceRow(name="alpha")
BETA = FakeSourceRow(name="beta")


def make_service() -> tuple[DeduplicationService, FakeJobRepository, FakeListingRepository, FakeCompanyRepository]:
    jobs = FakeJobRepository()
    listings = FakeListingRepository()
    jobs.listings = listings
    companies = FakeCompanyRepository()
    sources = FakeJobSourceRepository([ALPHA, BETA])
    return DeduplicationService(jobs, listings, companies, sources), jobs, listings, companies  # type: ignore[arg-type]


async def test_new_job_creates_company_job_and_primary_listing() -> None:
    service, jobs, listings, companies = make_service()

    result = await service.persist_batch(
        [make_normalized_job(source_name="alpha", external_id="1", company="Acme Pvt Ltd")]
    )

    assert (result.found, result.new, result.duplicate) == (1, 1, 0)
    assert len(jobs.jobs) == 1
    assert len(listings.listings) == 1 and listings.listings[0].isPrimary
    assert len(companies.companies) == 1
    assert len(result.new_job_ids) == 1


async def test_same_external_id_is_duplicate_and_refreshes_listing() -> None:
    service, jobs, listings, _ = make_service()
    job = make_normalized_job(source_name="alpha", external_id="1")
    await service.persist_batch([job])

    result = await service.persist_batch([job])

    assert (result.new, result.duplicate) == (0, 1)
    assert len(jobs.jobs) == 1
    assert len(listings.listings) == 1
    assert listings.refreshed  # the existing listing was refreshed, not recreated


async def test_cross_source_content_hash_attaches_secondary_listing() -> None:
    service, jobs, listings, _ = make_service()
    original = make_normalized_job(source_name="alpha", external_id="1")
    await service.persist_batch([original])

    mirrored = make_normalized_job(source_name="beta", external_id="b-9")
    result = await service.persist_batch([mirrored])

    assert (result.new, result.duplicate) == (0, 1)
    assert len(jobs.jobs) == 1
    assert len(listings.listings) == 2
    secondary = next(x for x in listings.listings if x.sourceId == BETA.id)
    assert secondary.isPrimary is False
    assert secondary.jobId == next(iter(jobs.jobs))


async def test_canonical_url_match_is_duplicate() -> None:
    service, jobs, _listings, _ = make_service()
    first = make_normalized_job(
        source_name="alpha",
        external_id="1",
        canonical_url="https://acme.dev/jobs/1",
        description="original text",
    )
    await service.persist_batch([first])

    # Different content (hash differs) but the same canonical URL.
    same_url = make_normalized_job(
        source_name="beta",
        external_id="x",
        canonical_url="https://acme.dev/jobs/1",
        description="reworded text",
    )
    result = await service.persist_batch([same_url])

    assert (result.new, result.duplicate) == (0, 1)
    assert len(jobs.jobs) == 1


async def test_in_batch_cross_source_duplicate() -> None:
    service, jobs, listings, _ = make_service()

    result = await service.persist_batch(
        [
            make_normalized_job(source_name="alpha", external_id="1"),
            make_normalized_job(source_name="beta", external_id="b-9"),  # same content
        ]
    )

    assert (result.found, result.new, result.duplicate) == (2, 1, 1)
    assert len(jobs.jobs) == 1
    assert len(listings.listings) == 2


async def test_company_reused_across_suffix_variants() -> None:
    service, _, _, companies = make_service()

    await service.persist_batch(
        [
            make_normalized_job(source_name="alpha", external_id="1", company="Acme Pvt Ltd"),
            make_normalized_job(
                source_name="alpha", external_id="2", company="Acme", title="Other Role"
            ),
        ]
    )

    assert len(companies.companies) == 1


async def test_rerun_is_fully_idempotent() -> None:
    service, jobs, _, _ = make_service()
    batch = [
        make_normalized_job(source_name="alpha", external_id="1"),
        make_normalized_job(source_name="alpha", external_id="2", title="Other Role"),
    ]
    first = await service.persist_batch(batch)
    second = await service.persist_batch(batch)

    assert (first.new, first.duplicate) == (2, 0)
    assert (second.new, second.duplicate) == (0, 2)
    assert len(jobs.jobs) == 2
