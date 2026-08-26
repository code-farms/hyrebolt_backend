"""Phase 13: company_careers emits only the metadata a board legitimately
provides — its public URL and an operator-supplied website."""

import httpx

from app.sources import DEFAULT_CONFIGS, SourceCapability, SourceSearchParams
from tests.sources.conftest import load_json_fixture, make_registry

BOARDS = [
    {
        "company": "AcmeCorp",
        "provider": "greenhouse",
        "token": "acmecorp",
        "website": "https://acme.example",
    },
    {"company": "Globex", "provider": "lever", "token": "globex"},
]


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "boards-api.greenhouse.io":
        return httpx.Response(200, json=load_json_fixture("greenhouse.json"))
    if request.url.host == "api.lever.co":
        return httpx.Response(200, json=load_json_fixture("lever.json"))
    raise AssertionError(f"unexpected host: {request.url}")


def make_connector():
    base = DEFAULT_CONFIGS["company_careers"]
    overrides = {"company_careers": base.model_copy(update={"extra": {"boards": BOARDS}})}
    return make_registry(handler, overrides=overrides).get("company_careers")


async def test_normalized_jobs_carry_board_url_and_source() -> None:
    connector = make_connector()
    normalized = [connector.normalize_job(raw) for raw in await connector.search_jobs(SourceSearchParams())]
    by_company = {job.companyName: job for job in normalized}

    acme = by_company["AcmeCorp"].company
    assert acme is not None
    assert acme.careersUrl == "https://boards.greenhouse.io/acmecorp"
    assert acme.website == "https://acme.example"
    assert acme.metadataSource == "company_careers"
    assert acme.stage is None and acme.industry is None  # never inferred

    globex = by_company["Globex"].company
    assert globex is not None
    assert globex.careersUrl == "https://jobs.lever.co/globex"
    assert globex.website is None


def test_connector_declares_startup_metadata_capability() -> None:
    assert SourceCapability.STARTUP_METADATA in DEFAULT_CONFIGS["company_careers"].capabilities
