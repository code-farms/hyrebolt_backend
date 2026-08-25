from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.api.deps import get_job_repository
from app.main import app
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


def make_job_row(
    job_id: str = "job-1",
    *,
    duplicate_of: str | None = None,
    duplicates: list[str] | None = None,
    deleted: bool = False,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=job_id,
        title="Backend Engineer",
        companyName="Acme",
        location="Bengaluru, India",
        country="IN",
        remote=False,
        hybrid=True,
        employmentType="FULL_TIME",
        experienceMin=2.0,
        experienceMax=5.0,
        salaryMin=2000000,
        salaryMax=3000000,
        salaryCurrency="INR",
        description="Build APIs",
        sourceUrl="https://remoteok.com/remote-jobs/1",
        canonicalUrl="https://remoteok.com/remote-jobs/1",
        postedAt=now,
        discoveredAt=now,
        createdAt=now,
        deletedAt=now if deleted else None,
        duplicateOfId=duplicate_of,
        duplicates=[SimpleNamespace(id=d) for d in (duplicates or [])],
        listings=[
            SimpleNamespace(
                source=SimpleNamespace(name="remoteok", displayName="Remote OK"),
                sourceUrl="https://remoteok.com/remote-jobs/1",
                canonicalUrl="https://remoteok.com/remote-jobs/1",
                externalId="1",
                isPrimary=True,
            ),
            SimpleNamespace(
                source=SimpleNamespace(name="weworkremotely", displayName="We Work Remotely"),
                sourceUrl="https://weworkremotely.com/remote-jobs/acme-backend",
                canonicalUrl=None,
                externalId="wwr-9",
                isPrimary=False,
            ),
        ],
    )


class FakeJobsRepo:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = {row.id: row for row in rows}

    async def list_active_with_listings(self, *, limit: int, offset: int):
        active = [r for r in self.rows.values() if r.deletedAt is None]
        return active[offset : offset + limit], len(active)

    async def get_with_listings(self, job_id: str):
        return self.rows.get(job_id)


@pytest.fixture
def jobs_repo():
    repo = FakeJobsRepo(
        [
            make_job_row("job-1", duplicates=["job-2"]),
            make_job_row("job-2", duplicate_of="job-1"),
            make_job_row("job-gone", deleted=True),
        ]
    )
    app.dependency_overrides[get_job_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_job_repository, None)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_jobs_require_auth(auth_client: AuthFixture, jobs_repo) -> None:
    client, _, _ = auth_client
    assert (await client.get("/api/v1/jobs")).status_code == 401
    assert (await client.get("/api/v1/jobs/job-1")).status_code == 401


async def test_list_jobs_exposes_source_information(
    auth_client: AuthFixture, jobs_repo
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/jobs?limit=10", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2  # soft-deleted job excluded
    first = body["items"][0]
    source_names = {s["sourceName"] for s in first["sources"]}
    assert source_names == {"remoteok", "weworkremotely"}
    primary = next(s for s in first["sources"] if s["isPrimary"])
    assert primary["sourceName"] == "remoteok"
    assert primary["url"] == "https://remoteok.com/remote-jobs/1"


async def test_get_job_exposes_duplicate_links(auth_client: AuthFixture, jobs_repo) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    primary = await client.get("/api/v1/jobs/job-1", headers=headers)
    linked = await client.get("/api/v1/jobs/job-2", headers=headers)

    assert primary.status_code == 200
    assert primary.json()["duplicateIds"] == ["job-2"]
    assert primary.json()["duplicateOfId"] is None
    assert linked.json()["duplicateOfId"] == "job-1"


async def test_get_job_404s(auth_client: AuthFixture, jobs_repo) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    assert (await client.get("/api/v1/jobs/missing", headers=headers)).status_code == 404
    # Soft-deleted jobs are invisible.
    assert (await client.get("/api/v1/jobs/job-gone", headers=headers)).status_code == 404
