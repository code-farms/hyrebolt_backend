"""Phase 13: turns watchlisted companies' careers URLs into company_careers
board configs, so the daily search discovers jobs on watched startups' own
Greenhouse/Lever boards. Injected into DiscoveryService as a plain callable
to keep the discovery engine persistence-agnostic."""

from app.repositories import CompanyRepository
from app.sources.boards import board_from_careers_url


class WatchlistBoardsProvider:
    def __init__(self, companies: CompanyRepository) -> None:
        self._companies = companies

    async def __call__(self) -> list[dict[str, str]]:
        boards: list[dict[str, str]] = []
        for name, url in await self._companies.list_watched_careers_urls():
            board = board_from_careers_url(name, url)
            if board is not None:
                boards.append(board)
        return boards
