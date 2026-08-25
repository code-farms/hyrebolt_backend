from app.core.config import get_settings
from app.services.deduplication_service import DeduplicationService
from app.services.duplicate_detection_service import DuplicateDetectionService
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
    settings = get_settings()
    service = DeduplicationService(
        jobs,  # type: ignore[arg-type]
        listings,  # type: ignore[arg-type]
        companies,  # type: ignore[arg-type]
        sources,  # type: ignore[arg-type]
        detector=DuplicateDetectionService(settings),
        settings=settings,
    )
    return service, jobs, listings, companies


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


async def test_fuzzy_title_variant_auto_merges() -> None:
    from datetime import UTC, datetime

    service, jobs, listings, _ = make_service()
    posted = datetime(2026, 8, 20, tzinfo=UTC)
    description = (
        "design build and operate the payment apis that power our merchant "
        "platform using python postgres and redis owning services end to end"
    )
    await service.persist_batch(
        [
            make_normalized_job(
                source_name="alpha",
                external_id="1",
                title="Backend Engineer",
                description=description,
                posted_at=posted,
                location="Bengaluru, India",
            )
        ]
    )

    variant = make_normalized_job(
        source_name="beta",
        external_id="b-1",
        title="Sr Backend Engineer",  # different hash, same opening
        description=description,
        posted_at=posted,
        location="Bengaluru, India",
    )
    result = await service.persist_batch([variant])

    assert (result.new, result.duplicate) == (0, 1)
    assert len(jobs.jobs) == 1
    assert len(listings.listings) == 2  # secondary listing attached


async def test_fuzzy_uncertain_match_links_without_merging() -> None:
    from datetime import UTC, datetime

    service, jobs, _, _ = make_service()
    posted = datetime(2026, 8, 20, tzinfo=UTC)
    await service.persist_batch(
        [
            make_normalized_job(
                source_name="alpha",
                external_id="1",
                title="Backend Engineer",
                description=None,
                posted_at=posted,
                location="Bengaluru",
            )
        ]
    )
    original_id = next(iter(jobs.jobs))

    # Same title/company/date, containment-matching location, no descriptions
    # to confirm — enough to relate, not enough to merge.
    uncertain = make_normalized_job(
        source_name="beta",
        external_id="b-1",
        title="Backend Engineer",
        description=None,
        posted_at=posted,
        location="Bengaluru, India",
    )
    result = await service.persist_batch([uncertain])

    assert (result.new, result.duplicate) == (1, 0)
    assert len(jobs.jobs) == 2
    linked = jobs.jobs[result.new_job_ids[0]]
    assert linked.duplicateOfId == original_id


async def test_fuzzy_distinct_role_stays_new_and_unlinked() -> None:
    service, jobs, _, _ = make_service()
    await service.persist_batch(
        [make_normalized_job(source_name="alpha", external_id="1", title="Backend Engineer")]
    )

    result = await service.persist_batch(
        [
            make_normalized_job(
                source_name="alpha",
                external_id="2",
                title="Product Designer",
                description="craft beautiful mobile design systems",
            )
        ]
    )

    assert (result.new, result.duplicate) == (1, 0)
    assert len(jobs.jobs) == 2
    assert jobs.jobs[result.new_job_ids[0]].duplicateOfId is None


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
