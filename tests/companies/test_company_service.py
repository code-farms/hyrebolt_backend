from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.models import WatchlistPriority
from app.schemas.company import WatchlistCreateIn
from tests.companies.fakes import make_harness

USER = SimpleNamespace(id="u1")
OTHER = SimpleNamespace(id="u2")


async def test_add_by_name_creates_company_with_user_metadata_and_rescores() -> None:
    h = make_harness()

    entry = await h.service.add_to_watchlist(
        USER,  # type: ignore[arg-type]
        WatchlistCreateIn(
            companyName="Acme Inc",
            priority=WatchlistPriority.HIGH,
            preferredRoles=[" Backend Engineer ", "Backend Engineer", ""],
            careersUrl="https://boards.greenhouse.io/acme",
        ),
    )

    assert entry.company.name == "Acme Inc"
    assert entry.company.careersUrl == "https://boards.greenhouse.io/acme"
    assert entry.company.metadataSource == "user"
    assert entry.priority == WatchlistPriority.HIGH
    assert entry.preferredRoles == ["Backend Engineer"]  # cleaned + deduped
    assert entry.company.watchlist is not None and entry.company.watchlist.id == entry.id
    company_id = entry.company.id
    assert h.matches.stale_calls == [("u1", company_id, "Acme Inc")]
    assert h.matching.rescored == [("u1", company_id, h.service._settings.match_batch_limit)]


async def test_add_existing_company_is_conflict() -> None:
    h = make_harness()
    company = h.companies.seed("Acme")
    await h.service.add_to_watchlist(USER, WatchlistCreateIn(companyId=company.id))  # type: ignore[arg-type]

    with pytest.raises(ConflictError):
        await h.service.add_to_watchlist(USER, WatchlistCreateIn(companyName="acme"))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await h.service.add_to_watchlist(USER, WatchlistCreateIn(companyId="missing"))  # type: ignore[arg-type]


async def test_update_and_remove_are_owner_scoped_and_rescore() -> None:
    h = make_harness()
    entry = await h.service.add_to_watchlist(USER, WatchlistCreateIn(companyName="Acme"))  # type: ignore[arg-type]
    h.matching.rescored.clear()

    updated = await h.service.update_entry(
        USER, entry.id, {"priority": WatchlistPriority.LOW, "excludedRoles": ["Sales"]}  # type: ignore[arg-type]
    )
    assert updated.priority == WatchlistPriority.LOW
    assert updated.excludedRoles == ["Sales"]
    assert len(h.matching.rescored) == 1

    with pytest.raises(NotFoundError):
        await h.service.update_entry(OTHER, entry.id, {"priority": WatchlistPriority.HIGH})  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await h.service.remove_entry(OTHER, entry.id)  # type: ignore[arg-type]

    await h.service.remove_entry(USER, entry.id)  # type: ignore[arg-type]
    assert h.watchlists.rows == {}
    assert len(h.matching.rescored) == 2
    assert (await h.service.list_watchlist(USER)).items == []  # type: ignore[arg-type]


async def test_watchlist_and_recent_jobs_carry_open_position_counts() -> None:
    h = make_harness()
    acme = h.companies.seed("Acme")
    globex = h.companies.seed("Globex")
    h.jobs.add("j1", acme.id)
    h.jobs.add("j2", acme.id)
    h.jobs.add("j3", globex.id)
    await h.service.add_to_watchlist(USER, WatchlistCreateIn(companyId=acme.id))  # type: ignore[arg-type]

    listed = await h.service.list_watchlist(USER)  # type: ignore[arg-type]
    assert listed.total == 1
    assert listed.items[0].company.openPositions == 2

    jobs, total = await h.service.recent_watchlist_jobs(USER, limit=10, offset=0)  # type: ignore[arg-type]
    assert total == 2 and {j.id for j in jobs} == {"j1", "j2"}

    company_jobs, company_total = await h.service.list_company_jobs(
        USER, globex.id, limit=10, offset=0  # type: ignore[arg-type]
    )
    assert company_total == 1 and company_jobs[0].id == "j3"

    companies = await h.service.list_companies(USER, query="ac", limit=10, offset=0)  # type: ignore[arg-type]
    assert [c.name for c in companies.items] == ["Acme"]
    assert companies.items[0].watchlist is not None
    detail = await h.service.get_company(USER, globex.id)  # type: ignore[arg-type]
    assert detail.watchlist is None and detail.openPositions == 1


async def test_metadata_edit_requires_watchlist_and_stamps_source() -> None:
    h = make_harness()
    company = h.companies.seed("Acme", industry="Fintech")

    with pytest.raises(NotFoundError):
        await h.service.update_metadata(USER, company.id, {"stage": "Seed"})  # type: ignore[arg-type]

    await h.service.add_to_watchlist(USER, WatchlistCreateIn(companyId=company.id))  # type: ignore[arg-type]
    out = await h.service.update_metadata(USER, company.id, {"stage": "Seed", "website": None})  # type: ignore[arg-type]

    assert out.stage == "Seed"
    assert out.industry == "Fintech"  # untouched
    assert out.website is None
    assert out.metadataSource == "user"


def test_create_payload_requires_exactly_one_company_reference() -> None:
    with pytest.raises(ValueError):
        WatchlistCreateIn()
    with pytest.raises(ValueError):
        WatchlistCreateIn(companyId="c1", companyName="Acme")
    with pytest.raises(ValueError):
        WatchlistCreateIn(companyName="Acme", careersUrl="not a url")
