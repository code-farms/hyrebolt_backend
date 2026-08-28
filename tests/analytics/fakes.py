"""In-memory stand-in for AnalyticsRepository: canned aggregates + recorded
call arguments, so the service and API tests never need Postgres."""

from datetime import datetime
from typing import Any


def engagement(found: int, relevant: int = 0, saved: int = 0, applied: int = 0, interviews: int = 0):
    return {
        "jobsFound": found,
        "relevant": relevant,
        "saved": saved,
        "applied": applied,
        "interviews": interviews,
    }


class FakeAnalyticsRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.discovery = {"discovered": 40, "analyzed": 30, "matched": 10}
        self.deduplicated = 12
        self.funnel = {"saved": 8, "applied": 6, "interviews": 2, "offers": 1, "rejected": 3}
        self.sources: list[dict[str, Any]] = [
            {"name": "remoteok", "displayName": "Remote OK", **engagement(30, 8, 5, 4, 2)},
            {"name": "linkedin", "displayName": "LinkedIn", **engagement(10, 2, 1, 0, 0)},
        ]
        self.titles: list[dict[str, Any]] = [
            {"title": "senior backend engineer", **engagement(12, 4, 2, 2, 1)},
            {"title": "python developer", **engagement(8, 3, 1, 1, 0)},
            {"title": "react developer", **engagement(6, 2, 1, 1, 1)},
            {"title": "account executive", **engagement(3)},
        ]
        self.companies: list[dict[str, Any]] = [
            {"companyId": "c1", "companyName": "Acme", **engagement(5, 3, 2, 2, 1)},
            {"companyId": None, "companyName": "Globex", **engagement(2, 1, 1, 0, 0)},
        ]
        self.daily_jobs_rows: list[dict[str, Any]] = []
        self.daily_event_rows: list[dict[str, Any]] = []

    async def discovery_counts(self, user_id: str, since: datetime, threshold: float):
        self.calls.append(("discovery_counts", (user_id, since, threshold)))
        return dict(self.discovery)

    async def deduplicated_count(self, since: datetime):
        self.calls.append(("deduplicated_count", (since,)))
        return self.deduplicated

    async def application_funnel(self, user_id: str, since: datetime):
        self.calls.append(("application_funnel", (user_id, since)))
        return dict(self.funnel)

    async def source_performance(self, user_id: str, since: datetime, threshold: float):
        self.calls.append(("source_performance", (user_id, since, threshold)))
        return [dict(row) for row in self.sources]

    async def title_performance(self, user_id: str, since: datetime, threshold: float):
        self.calls.append(("title_performance", (user_id, since, threshold)))
        return [dict(row) for row in self.titles]

    async def company_performance(
        self, user_id: str, since: datetime, threshold: float, limit: int
    ):
        self.calls.append(("company_performance", (user_id, since, threshold, limit)))
        return [dict(row) for row in self.companies[:limit]]

    async def daily_jobs(self, user_id: str, since: datetime, tz_name: str, threshold: float):
        self.calls.append(("daily_jobs", (user_id, since, tz_name, threshold)))
        return [dict(row) for row in self.daily_jobs_rows]

    async def daily_application_events(self, user_id: str, since: datetime, tz_name: str):
        self.calls.append(("daily_application_events", (user_id, since, tz_name)))
        return [dict(row) for row in self.daily_event_rows]
