from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.api.deps import (
    get_application_repository,
    get_job_match_repository,
    get_job_repository,
    get_job_source_repository,
    get_saved_job_repository,
)
from app.main import app
from app.models import ApplicationStatus
from app.repositories.job_repository import JobFilters, _job_where
from tests.discovery.test_jobs_api import make_job_row
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


class RecordingJobsRepo:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.filtered_calls: list[JobFilters] = []
        self.score_calls: list[tuple[JobFilters, float]] = []

    async def list_filtered(self, user_id, filters, *, limit, offset):
        self.filtered_calls.append(filters)
        return self.rows[offset : offset + limit], len(self.rows)

    async def list_by_score(self, user_id, filters, *, min_score, limit, offset):
        self.score_calls.append((filters, min_score))
        matches = [SimpleNamespace(job=row, overallScore=90 - i) for i, row in enumerate(self.rows)]
        return matches[offset : offset + limit], len(matches)

    async def get_with_listings(self, job_id):
        return next((r for r in self.rows if r.id == job_id), None)

    async def count_created_since(self, since):
        return 4


class FakeSavedRepo:
    def __init__(self) -> None:
        self.saved: set[tuple[str, str]] = set()

    async def save(self, user_id, job_id):
        self.saved.add((user_id, job_id))

    async def unsave(self, user_id, job_id):
        self.saved.discard((user_id, job_id))
        return 1

    async def is_saved(self, user_id, job_id):
        return (user_id, job_id) in self.saved

    async def list_for_user(self, user_id, *, limit, offset):
        rows = [
            SimpleNamespace(job=make_job_row(job_id))
            for (uid, job_id) in sorted(self.saved)
            if uid == user_id
        ]
        return rows[offset : offset + limit], len(rows)

    async def count_for_user(self, user_id):
        return sum(1 for uid, _ in self.saved if uid == user_id)


class FakeMatchesRepo:
    async def count_in_score_band(self, user_id, *, min_score, max_score=None):
        return 3 if max_score is None else 5


class FakeApplicationsRepo:
    async def count_for_user(self, user_id, *, status=None):
        return 2 if status == ApplicationStatus.INTERVIEW else 7


class FakeSourcesRepo:
    async def list_all(self):
        return [
            SimpleNamespace(name="remoteok", displayName="Remote OK", enabled=True),
            SimpleNamespace(name="linkedin", displayName="LinkedIn", enabled=False),
        ]


@pytest.fixture
def phase11_overrides():
    jobs_repo = RecordingJobsRepo([make_job_row("j1"), make_job_row("j2")])
    saved_repo = FakeSavedRepo()
    app.dependency_overrides[get_job_repository] = lambda: jobs_repo
    app.dependency_overrides[get_saved_job_repository] = lambda: saved_repo
    app.dependency_overrides[get_job_match_repository] = lambda: FakeMatchesRepo()
    app.dependency_overrides[get_application_repository] = lambda: FakeApplicationsRepo()
    app.dependency_overrides[get_job_source_repository] = lambda: FakeSourcesRepo()
    yield jobs_repo, saved_repo
    for dep in (
        get_job_repository,
        get_saved_job_repository,
        get_job_match_repository,
        get_application_repository,
        get_job_source_repository,
    ):
        app.dependency_overrides.pop(dep, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_filters_are_parsed_into_job_filters(
    auth_client: AuthFixture, phase11_overrides
) -> None:
    client, _, _ = auth_client
    jobs_repo, _ = phase11_overrides
    headers = await _login(client)

    response = await client.get(
        "/api/v1/jobs?source=remoteok&location=bengaluru&remote=true&company=acme"
        "&minSalary=100000&maxExperience=5&skills=python,%20react&datePosted=7",
        headers=headers,
    )

    assert response.status_code == 200
    filters = jobs_repo.filtered_calls[0]
    assert filters.source == "remoteok"
    assert filters.location == "bengaluru"
    assert filters.remote is True
    assert filters.company == "acme"
    assert filters.min_salary == 100000
    assert filters.max_experience == 5
    assert filters.skills == ("python", "react")
    assert filters.date_posted_days == 7


async def test_score_sort_and_min_score_use_match_path(
    auth_client: AuthFixture, phase11_overrides
) -> None:
    client, _, _ = auth_client
    jobs_repo, _ = phase11_overrides
    headers = await _login(client)

    by_sort = await client.get("/api/v1/jobs?sort=score", headers=headers)
    by_min = await client.get("/api/v1/jobs?minScore=70", headers=headers)

    assert by_sort.status_code == 200 and by_min.status_code == 200
    assert len(jobs_repo.score_calls) == 2
    assert jobs_repo.score_calls[0][1] == 0  # sort=score without minScore
    assert jobs_repo.score_calls[1][1] == 70
    assert jobs_repo.filtered_calls == []


async def test_save_unsave_and_saved_list(auth_client: AuthFixture, phase11_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    saved = await client.post("/api/v1/jobs/j1/save", headers=headers)
    assert saved.status_code == 200 and saved.json()["saved"] is True

    again = await client.post("/api/v1/jobs/j1/save", headers=headers)  # idempotent
    assert again.status_code == 200

    listing = await client.get("/api/v1/jobs/saved", headers=headers)
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["saved"] is True

    removed = await client.delete("/api/v1/jobs/j1/save", headers=headers)
    assert removed.status_code == 200 and removed.json()["saved"] is False
    assert (await client.get("/api/v1/jobs/saved", headers=headers)).json()["total"] == 0

    assert (await client.post("/api/v1/jobs/nope/save", headers=headers)).status_code == 404


async def test_dashboard_stats_shape(auth_client: AuthFixture, phase11_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/dashboard/stats", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "newJobsToday": 4,
        "excellentMatches": 3,
        "strongMatches": 5,
        "savedJobs": 0,
        "applications": 7,
        "interviews": 2,
    }


async def test_sources_endpoint(auth_client: AuthFixture, phase11_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/sources", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {"name": "linkedin", "displayName": "LinkedIn", "enabled": False},
        {"name": "remoteok", "displayName": "Remote OK", "enabled": True},
    ]


async def test_auth_required(auth_client: AuthFixture, phase11_overrides) -> None:
    client, _, _ = auth_client
    for method, path in (
        ("get", "/api/v1/dashboard/stats"),
        ("get", "/api/v1/sources"),
        ("get", "/api/v1/jobs/saved"),
        ("post", "/api/v1/jobs/j1/save"),
        ("delete", "/api/v1/jobs/j1/save"),
    ):
        response = await getattr(client, method)(path)
        assert response.status_code == 401


def test_job_where_builder() -> None:
    where = _job_where(
        JobFilters(
            source="remoteok",
            location="pune",
            remote=False,
            company="acme",
            min_salary=50,
            skills=("python", "react"),
        )
    )
    assert where["source"] == {"is": {"name": "remoteok"}}
    assert where["remote"] is False
    assert where["salaryMax"] == {"gte": 50}
    assert len(where["AND"]) == 2  # one OR-block per skill term
    assert where["deletedAt"] is None


