"""Phase 13: persistence fills Company metadata null-only, even for jobs
that dedup recognises as already known."""

from app.sources import CompanyMetadata
from tests.discovery.fakes import make_normalized_job
from tests.discovery.test_dedup_service import make_service


async def test_metadata_fills_nulls_and_never_overwrites() -> None:
    service, _jobs, _listings, companies = make_service()

    first = make_normalized_job(
        source_name="alpha",
        external_id="1",
        company="Acme",
        company_metadata=CompanyMetadata(
            careersUrl="https://boards.greenhouse.io/acme", metadataSource="company_careers"
        ),
    )
    await service.persist_batch([first])
    (company,) = companies.companies.values()
    assert company.careersUrl == "https://boards.greenhouse.io/acme"
    assert company.metadataSource == "company_careers"
    assert company.website is None

    # Same listing seen again (duplicate path) with more metadata: only the
    # still-null column is filled.
    again = make_normalized_job(
        source_name="alpha",
        external_id="1",
        company="Acme",
        company_metadata=CompanyMetadata(
            careersUrl="https://jobs.lever.co/acme",
            website="https://acme.example",
            metadataSource="other",
        ),
    )
    result = await service.persist_batch([again])

    assert result.duplicate == 1
    assert company.careersUrl == "https://boards.greenhouse.io/acme"  # unchanged
    assert company.metadataSource == "company_careers"  # unchanged
    assert company.website == "https://acme.example"  # filled
    assert company.stage is None  # never invented


async def test_jobs_without_metadata_leave_company_untouched() -> None:
    service, _jobs, _listings, companies = make_service()
    await service.persist_batch([make_normalized_job(source_name="alpha", company="Acme")])
    (company,) = companies.companies.values()
    assert company.careersUrl is None and company.metadataSource is None
