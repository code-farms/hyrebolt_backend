import pytest
from httpx import AsyncClient

from app.api.deps import (
    get_job_match_repository,
    get_job_repository,
    get_matching_service,
    get_ranking_service,
)
from app.main import app
from app.models import MatchFeedback, MatchRecommendation
from app.services.ranking_service import RankingService
from tests.fakes import FakeDB, FakeRedis
from tests.matching.fakes import FakeJobMatchRepository, FakeMatchRow, make_match_job

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


def seed_match(
    repo: FakeJobMatchRepository,
    job,
    *,
    user_id: str,
    score: float,
    feedback: MatchFeedback | None = None,
) -> FakeMatchRow:
    row = FakeMatchRow(
        id=f"m-{job.id}",
        userId=user_id,
        jobId=job.id,
        overallScore=score,
        recommendation=MatchRecommendation.CONSIDER,
        scoringVersion="rules-v1",
        feedback=feedback,
        job=augment_job(job),
    )
    repo.rows[(user_id, job.id)] = row
    return row


def augment_job(job):
    # jobs_api-compatible shape: listings/duplicates/analysis for job_out().
    job.country = None
    job.employmentType = None
    job.salaryMin = None
    job.sourceUrl = None
    job.canonicalUrl = None
    job.postedAt = None
    job.discoveredAt = job.createdAt
    job.duplicateOfId = None
    job.duplicates = []
    job.listings = []
    return job


async def test_ranking_orders_filters_and_excludes_not_relevant() -> None:
    jobs = [make_match_job(job_id=f"j{i}") for i in range(4)]
    repo = FakeJobMatchRepository({j.id: j for j in jobs})
    seed_match(repo, jobs[0], user_id="u1", score=90)
    seed_match(repo, jobs[1], user_id="u1", score=40)
    seed_match(repo, jobs[2], user_id="u1", score=70, feedback=MatchFeedback.NOT_RELEVANT)
    seed_match(repo, jobs[3], user_id="other", score=99)

    class U:
        id = "u1"

    ranking = RankingService(repo)  # type: ignore[arg-type]
    rows, total = await ranking.recommended(U(), limit=10, offset=0, min_score=50)  # type: ignore[arg-type]

    assert total == 1  # 40 filtered by min_score, NOT_RELEVANT hidden, other user's hidden
    assert rows[0].match.jobId == "j0"
    assert rows[0].ranking.finalScore == 90 and rows[0].ranking.explanations == []

    all_rows, all_total = await ranking.recommended(U(), limit=10, offset=0, min_score=0)  # type: ignore[arg-type]
    assert all_total == 2
    assert [r.match.overallScore for r in all_rows] == [90, 40]


class StubMatchingService:
    def __init__(self) -> None:
        self.ensure_calls = 0

    async def ensure_matches_for_user(self, user, *, limit: int) -> int:
        self.ensure_calls += 1
        return 0


@pytest.fixture
def api_overrides():
    jobs = [make_match_job(job_id="j1"), make_match_job(job_id="j2", title="Data Engineer")]
    repo = FakeJobMatchRepository({j.id: j for j in jobs})
    stub_matching = StubMatchingService()

    class FakeJobsRepo:
        async def get_by_id(self, job_id: str):
            return next((j for j in jobs if j.id == job_id), None)

        async def get_with_listings(self, job_id: str):
            job = await self.get_by_id(job_id)
            return augment_job(job) if job else None

    app.dependency_overrides[get_job_match_repository] = lambda: repo
    app.dependency_overrides[get_ranking_service] = lambda: RankingService(repo)  # type: ignore[arg-type]
    app.dependency_overrides[get_matching_service] = lambda: RealishMatching(repo, jobs)
    app.dependency_overrides[get_job_repository] = lambda: FakeJobsRepo()
    yield repo, jobs, stub_matching
    for dep in (
        get_job_match_repository,
        get_ranking_service,
        get_matching_service,
        get_job_repository,
    ):
        app.dependency_overrides.pop(dep, None)


class RealishMatching:
    """Enough of CandidateMatchingService for the API routes."""

    def __init__(self, repo: FakeJobMatchRepository, jobs) -> None:
        self._repo = repo
        self._jobs = {j.id: j for j in jobs}

    async def ensure_matches_for_user(self, user, *, limit: int) -> int:
        for job in self._jobs.values():
            if (user.id, job.id) not in self._repo.rows:
                seed_match(self._repo, job, user_id=user.id, score=77)
        return 0

    async def match_job(self, user, job, *, force: bool = False):
        row = self._repo.rows.get((user.id, job.id))
        if row is None:
            row = seed_match(self._repo, job, user_id=user.id, score=77)
        return row

    async def record_feedback(self, user, job, feedback):
        row = await self.match_job(user, job)
        return await self._repo.set_feedback(row.id, feedback)


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_endpoints_require_auth(auth_client: AuthFixture, api_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.get("/api/v1/jobs/recommended")).status_code == 401
    assert (await client.get("/api/v1/jobs/j1/match")).status_code == 401
    assert (
        await client.post("/api/v1/jobs/j1/feedback", json={"feedback": "positive"})
    ).status_code == 401


async def test_recommended_returns_ranked_job_match_pairs(
    auth_client: AuthFixture, api_overrides
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.get("/api/v1/jobs/recommended?limit=10", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    first = body["items"][0]
    assert {"job", "match", "ranking"} <= set(first)
    assert first["match"]["overallScore"] == 77
    assert first["ranking"]["finalScore"] == 77 and first["job"]["ranking"]["baseScore"] == 77
    assert first["match"]["componentScores"].keys() >= {"role", "skill", "company"}
    assert first["job"]["id"] in ("j1", "j2")


async def test_job_match_and_feedback_roundtrip(
    auth_client: AuthFixture, api_overrides
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    match = await client.get("/api/v1/jobs/j1/match", headers=headers)
    assert match.status_code == 200
    assert match.json()["jobId"] == "j1"

    feedback = await client.post(
        "/api/v1/jobs/j1/feedback", json={"feedback": "notRelevant"}, headers=headers
    )
    assert feedback.status_code == 200
    assert feedback.json()["feedback"] == "NOT_RELEVANT"

    # NOT_RELEVANT jobs disappear from recommendations.
    recommended = await client.get("/api/v1/jobs/recommended", headers=headers)
    ids = [item["job"]["id"] for item in recommended.json()["items"]]
    assert "j1" not in ids


async def test_feedback_validation_and_404(auth_client: AuthFixture, api_overrides) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    bad = await client.post(
        "/api/v1/jobs/j1/feedback", json={"feedback": "meh"}, headers=headers
    )
    assert bad.status_code == 422

    missing = await client.get("/api/v1/jobs/nope/match", headers=headers)
    assert missing.status_code == 404
