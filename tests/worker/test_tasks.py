import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from app.core.config import get_settings
from app.models import SearchRunStatus, SearchTrigger
from app.worker import tasks as task_module
from app.worker.tasks import AgentTasks
from tests.fakes import FakeRedis
from tests.matching.fakes import FakeMatchRow

settings = get_settings()

TODAY = date(2026, 8, 25)


class FakeUsersRepo:
    def __init__(self, users: list[Any]) -> None:
        self.users = users

    async def list_active(self):
        return self.users


class FakeProfilesRepo:
    def __init__(self, profiles: dict[str, Any]) -> None:
        self.profiles = profiles

    async def get_by_user_id(self, user_id: str):
        return self.profiles.get(user_id)


class FakeDiscovery:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def run_search(self, *, user_id, query, trigger):
        self.calls.append((user_id, query, trigger))
        return SimpleNamespace(
            id=uuid.uuid4().hex,
            status=SearchRunStatus.COMPLETED,
            jobsNew=3,
            jobsDuplicate=1,
        )


class FakeAnalysis:
    async def analyze_unanalyzed(self, *, limit: int) -> int:
        return 5


class FakeMatching:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.calls: list[str] = []

    async def ensure_matches_for_user(self, user, *, limit: int) -> int:
        self.calls.append(user.id)
        if user.id in self.fail_for:
            raise RuntimeError("boom")
        return 4


class FakeRanking:
    def __init__(self, rows_by_user: dict[str, list[FakeMatchRow]]) -> None:
        self.rows_by_user = rows_by_user
        self.last_args: dict[str, Any] = {}

    async def recommended(self, user, *, limit, offset, min_score):
        self.last_args = {"limit": limit, "min_score": min_score}
        rows = [
            r for r in self.rows_by_user.get(user.id, []) if r.overallScore >= min_score
        ]
        return rows[:limit], len(rows)


class FakeNotifications:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def create_if_absent(self, *, dedupe_key: str, **kwargs: Any):
        if dedupe_key in self.rows:
            return self.rows[dedupe_key], False
        self.rows[dedupe_key] = {"dedupeKey": dedupe_key, **kwargs}
        return self.rows[dedupe_key], True

    async def count_since(self, since):
        return len(self.rows)


def make_user(user_id: str):
    return SimpleNamespace(id=user_id)


def make_profile(
    *, roles: list[str], locations: list[str], digest_enabled: bool = True, max_jobs: int = 10
):
    return SimpleNamespace(
        targetRoles=roles,
        preferredLocations=locations,
        dailyDigestEnabled=digest_enabled,
        digestMaxJobs=max_jobs,
    )


def match_row(job_id: str, score: float) -> FakeMatchRow:
    row = FakeMatchRow(id=f"m-{job_id}", userId="u1", jobId=job_id, overallScore=score)
    row.job = SimpleNamespace(title=f"Job {job_id}", companyName="Acme")
    row.recommendation = None
    return row


def build_agent(
    *,
    users=None,
    profiles=None,
    matching=None,
    ranking=None,
) -> tuple[AgentTasks, FakeDiscovery, FakeNotifications, FakeRedis]:
    discovery = FakeDiscovery()
    notifications = FakeNotifications()
    redis = FakeRedis()
    agent = AgentTasks(
        discovery=discovery,  # type: ignore[arg-type]
        analysis=FakeAnalysis(),  # type: ignore[arg-type]
        matching=matching or FakeMatching(),  # type: ignore[arg-type]
        ranking=ranking or FakeRanking({}),  # type: ignore[arg-type]
        users=users or FakeUsersRepo([make_user("u1")]),  # type: ignore[arg-type]
        profiles=profiles
        or FakeProfilesRepo({"u1": make_profile(roles=["Backend Engineer"], locations=["Remote"])}),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        settings=settings,
    )
    return agent, discovery, notifications, redis


async def test_daily_search_runs_once_per_day() -> None:
    agent, discovery, _, _ = build_agent()

    first = await agent.run_daily_search(today=TODAY)
    second = await agent.run_daily_search(today=TODAY)

    assert first["executed"] is True
    assert second["executed"] is False  # date-key guard
    assert len(discovery.calls) == 1
    user_id, query, trigger = discovery.calls[0]
    assert user_id is None and trigger == SearchTrigger.SCHEDULED
    assert query.targetRoles == ["Backend Engineer"]


async def test_aggregate_query_unions_profiles() -> None:
    users = FakeUsersRepo([make_user("u1"), make_user("u2"), make_user("u3")])
    profiles = FakeProfilesRepo(
        {
            "u1": make_profile(roles=["Backend Engineer"], locations=["Bengaluru"]),
            "u2": make_profile(roles=["Backend Engineer", "Data Engineer"], locations=["Remote"]),
            # u3 has no profile
        }
    )
    agent, _, _, _ = build_agent(users=users, profiles=profiles)

    query = await agent.build_aggregate_query()

    assert query.targetRoles == ["Backend Engineer", "Data Engineer"]  # deduped, ordered
    assert query.locations == ["Bengaluru", "Remote"]
    assert query.limitPerSource == settings.discovery_max_jobs_per_source


async def test_digest_dedupes_filters_and_caps() -> None:
    rows = [match_row("j1", 90), match_row("j2", 70), match_row("j3", 30)]
    ranking = FakeRanking({"u1": rows})
    agent, _, notifications, _ = build_agent(ranking=ranking)

    first = await agent.send_daily_digest(today=TODAY)
    second = await agent.send_daily_digest(today=TODAY)

    assert first == {"created": 1, "skipped": 0}
    assert second == {"created": 0, "skipped": 1}  # dedupeKey blocked re-send
    assert len(notifications.rows) == 1
    row = notifications.rows[f"digest:u1:{TODAY.isoformat()}"]
    items = row["payload"]["items"]
    assert [i["jobId"] for i in items] == ["j1", "j2"]  # j3 under min score
    assert ranking.last_args["min_score"] == settings.min_match_score


async def test_digest_respects_profile_cap_and_toggle() -> None:
    rows = [match_row(f"j{i}", 90) for i in range(8)]
    ranking = FakeRanking({"u1": rows})
    profiles = FakeProfilesRepo(
        {"u1": make_profile(roles=[], locations=[], max_jobs=2)}
    )
    agent, _, notifications, _ = build_agent(ranking=ranking, profiles=profiles)
    await agent.send_daily_digest(today=TODAY)
    key = f"digest:u1:{TODAY.isoformat()}"
    assert len(notifications.rows[key]["payload"]["items"]) == 2  # profile cap wins

    disabled_profiles = FakeProfilesRepo(
        {"u1": make_profile(roles=[], locations=[], digest_enabled=False)}
    )
    agent2, _, notifications2, _ = build_agent(ranking=ranking, profiles=disabled_profiles)
    result = await agent2.send_daily_digest(today=TODAY)
    assert result == {"created": 0, "skipped": 0}
    assert notifications2.rows == {}


async def test_match_jobs_survives_one_user_failing() -> None:
    users = FakeUsersRepo([make_user("u1"), make_user("u2")])
    profiles = FakeProfilesRepo(
        {
            "u1": make_profile(roles=[], locations=[]),
            "u2": make_profile(roles=[], locations=[]),
        }
    )
    matching = FakeMatching(fail_for={"u1"})
    agent, _, _, _ = build_agent(users=users, profiles=profiles, matching=matching)

    total = await agent.match_jobs()

    assert matching.calls == ["u1", "u2"]  # continued past the failure
    assert total == 4


class RecordingArq:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str | None]] = []

    async def enqueue_job(self, name: str, *args: Any, _job_id: str | None = None, **kwargs: Any):
        self.enqueued.append((name, _job_id))
        return SimpleNamespace(job_id=_job_id)


async def test_chain_enqueues_with_deterministic_job_ids() -> None:
    agent, _, _, _ = build_agent()
    arq_redis = RecordingArq()
    ctx = {"agent": agent, "redis": arq_redis, "job_try": 1, "max_tries": 3}

    result = await task_module.daily_job_search(ctx)
    await task_module.analyze_new_jobs(ctx)
    await task_module.match_jobs(ctx)

    today = datetime.now(UTC).date().isoformat()
    assert result["executed"] is True
    names_ids = arq_redis.enqueued
    assert names_ids[0] == ("analyze_new_jobs", f"analyze:{result['date']}")
    assert names_ids[1] == ("match_jobs", f"match:{today}")
    assert names_ids[2] == ("send_daily_digest", f"digest:{today}")


async def test_skipped_daily_run_does_not_chain() -> None:
    agent, _, _, _ = build_agent()
    arq_redis = RecordingArq()
    ctx = {"agent": agent, "redis": arq_redis, "job_try": 1, "max_tries": 3}

    await task_module.daily_job_search(ctx)
    arq_redis.enqueued.clear()
    result = await task_module.daily_job_search(ctx)  # same day again

    assert result["executed"] is False
    assert arq_redis.enqueued == []


def test_worker_settings_registration() -> None:
    from app.worker.settings import WorkerSettings

    names = {fn.__name__ for fn in WorkerSettings.functions}
    assert names == {"daily_job_search", "analyze_new_jobs", "match_jobs", "send_daily_digest"}
    assert len(WorkerSettings.cron_jobs) == 1
    assert WorkerSettings.max_tries == 3
