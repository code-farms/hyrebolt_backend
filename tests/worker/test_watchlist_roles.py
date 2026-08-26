"""Phase 13: watchlist preferred roles feed the daily aggregate search so the
keyword-filtered career boards surface the jobs users actually want."""

from tests.worker.test_tasks import build_agent


class FakeWatchlists:
    def __init__(self, roles: list[str]) -> None:
        self.roles = roles

    async def list_all_preferred_roles(self) -> list[str]:
        return self.roles


async def test_aggregate_query_includes_watchlist_preferred_roles() -> None:
    agent, _, _, _ = build_agent()
    agent._watchlists = FakeWatchlists(["Platform Engineer", "Backend Engineer"])  # type: ignore[assignment]

    query = await agent.build_aggregate_query()

    assert query.targetRoles == ["Backend Engineer", "Platform Engineer"]  # deduped


async def test_aggregate_query_without_watchlist_repo_is_unchanged() -> None:
    agent, _, _, _ = build_agent()
    query = await agent.build_aggregate_query()
    assert query.targetRoles == ["Backend Engineer"]
