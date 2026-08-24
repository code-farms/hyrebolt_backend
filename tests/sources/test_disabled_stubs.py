from datetime import UTC, datetime

import pytest

from app.sources import RawJob, SourceDisabledError, SourceSearchParams
from tests.sources.conftest import make_registry, no_network_handler

DISABLED_SOURCES = [
    "linkedin",
    "naukri",
    "indeed",
    "cutshort",
    "wellfound",
    "ycombinator",
    "instahyre",
    "foundit",
]


@pytest.fixture
def registry():
    return make_registry(no_network_handler)


@pytest.mark.parametrize("name", DISABLED_SOURCES)
async def test_search_raises_disabled_with_reason(registry, name: str) -> None:
    connector = registry.get(name)

    with pytest.raises(SourceDisabledError) as excinfo:
        await connector.search_jobs(SourceSearchParams())

    assert excinfo.value.source_name == name
    assert excinfo.value.message  # a documented reason, not an empty string
    assert excinfo.value.retryable is False


@pytest.mark.parametrize("name", DISABLED_SOURCES)
async def test_normalize_and_details_also_refuse(registry, name: str) -> None:
    connector = registry.get(name)
    raw = RawJob(sourceName=name, payload={}, fetchedAt=datetime.now(UTC))

    with pytest.raises(SourceDisabledError):
        connector.normalize_job(raw)
    with pytest.raises(SourceDisabledError):
        await connector.get_job_details(raw)


@pytest.mark.parametrize("name", DISABLED_SOURCES)
async def test_health_check_reports_disabled_without_raising(registry, name: str) -> None:
    health = await registry.get(name).health_check()

    assert health.healthy is False
    assert health.detail is not None and health.detail.startswith("disabled:")


@pytest.mark.parametrize("name", DISABLED_SOURCES)
def test_disabled_sources_are_disabled_in_default_config(registry, name: str) -> None:
    assert registry.get_config(name).enabled is False
