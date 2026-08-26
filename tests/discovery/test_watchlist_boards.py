"""Phase 13: watchlist-derived boards join the company_careers config at
search time; the lookup can never sink a run."""

from app.models import SearchRunStatus
from app.schemas.search import SearchQuery
from app.services.watchlist_boards import WatchlistBoardsProvider
from app.sources import JobSourceConfig
from tests.discovery.fakes import StubConnector, make_normalized_job

CONFIGURED = {"company": "Ops Co", "provider": "greenhouse", "token": "opsco"}


def careers_stub() -> StubConnector:
    config = JobSourceConfig(
        name="company_careers",
        displayName="Company career pages",
        enabled=True,
        extra={"boards": [CONFIGURED]},
    )
    return StubConnector(
        "company_careers",
        config,
        jobs=[make_normalized_job(source_name="company_careers", company="Ops Co")],
    )


async def test_watchlist_boards_are_merged_into_the_connector_config(make_harness) -> None:
    connector = careers_stub()
    harness = make_harness({"company_careers": connector})

    async def provider() -> list[dict[str, str]]:
        return [
            {"company": "Acme", "provider": "lever", "token": "acme"},
            {"company": "Ops Co (dup)", "provider": "greenhouse", "token": "OPSCO"},
        ]

    harness.service._board_provider = provider

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.COMPLETED
    assert connector.config.extra["boards"] == [
        CONFIGURED,
        {"company": "Acme", "provider": "lever", "token": "acme"},
    ]


async def test_provider_failure_keeps_configured_boards(make_harness) -> None:
    connector = careers_stub()
    harness = make_harness({"company_careers": connector})

    async def broken() -> list[dict[str, str]]:
        raise RuntimeError("db down")

    harness.service._board_provider = broken

    run = await harness.service.run_search(user_id="u1", query=SearchQuery())

    assert run.status == SearchRunStatus.COMPLETED
    assert connector.config.extra["boards"] == [CONFIGURED]


async def test_boards_provider_maps_watched_companies() -> None:
    class Companies:
        async def list_watched_careers_urls(self, *, limit: int = 200):
            return [
                ("Acme", "https://boards.greenhouse.io/acme"),
                ("Plain", "https://plain.example/careers"),
                ("Globex", "https://jobs.lever.co/globex"),
            ]

    boards = await WatchlistBoardsProvider(Companies())()  # type: ignore[arg-type]
    assert boards == [
        {"company": "Acme", "provider": "greenhouse", "token": "acme"},
        {"company": "Globex", "provider": "lever", "token": "globex"},
    ]
