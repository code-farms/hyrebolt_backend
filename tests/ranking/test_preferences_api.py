import pytest
from httpx import AsyncClient

from app.api.deps import (
    get_application_repository,
    get_application_service,
    get_job_match_repository,
    get_job_repository,
    get_matching_service,
    get_preference_signal_service,
    get_ranking_service,
    get_saved_job_repository,
)
from app.main import app
from app.services.application_service import ApplicationService
from app.services.ranking_service import RankingService
from tests.applications.fakes import FakeApplicationRepository
from tests.fakes import FakeDB, FakeRedis
from tests.ranking.fakes import (
    FakeCandidateMatches,
    FakeJobsByScore,
    make_job,
    make_match,
    make_signal_service,
)

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]


class FakeSaved:
    def __init__(self) -> None:
        self.saved: set[tuple[str, str]] = set()

    async def save(self, user_id: str, job_id: str) -> None:
        self.saved.add((user_id, job_id))

    async def unsave(self, user_id: str, job_id: str) -> None:
        self.saved.discard((user_id, job_id))

    async def is_saved(self, user_id: str, job_id: str) -> bool:
        return (user_id, job_id) in self.saved


class FakeJobsRepo:
    def __init__(self, jobs) -> None:
        self.jobs = {j.id: j for j in jobs}

    async def get_by_id(self, job_id: str):
        return self.jobs.get(job_id)

    async def get_with_listings(self, job_id: str):
        return self.jobs.get(job_id)


class MatchesWithFeedback(FakeCandidateMatches):
    """FakeCandidateMatches whose rows live in a dict keyed by (user, job), so
    the matching stub can seed matches lazily like the real service does."""

    def __init__(self) -> None:
        super().__init__([])
        self.rows_by_key: dict[tuple[str, str], object] = {}

    @property
    def rows(self):  # type: ignore[override]
        return list(self.rows_by_key.values())

    @rows.setter
    def rows(self, value) -> None:  # FakeCandidateMatches.__init__ assigns []
        pass


@pytest.fixture
def ranking_overrides():
    acme = make_job(job_id="j-acme", title="Backend Engineer", company="Acme", posted_days_ago=30)
    globex = make_job(job_id="j-globex", title="Backend Engineer", company="Globex", posted_days_ago=30)
    zed = make_job(job_id="j-zed", title="Product Designer", company="Zed", posted_days_ago=30)
    jobs = [acme, globex, zed]
    repo = MatchesWithFeedback()

    class Matching:
        """Enough of CandidateMatchingService for the routes under test."""

        async def ensure_matches_for_user(self, user, *, limit: int) -> int:
            for job in jobs:
                repo.rows_by_key.setdefault(
                    (user.id, job.id), make_match(job, user_id=user.id, score=77, company_score=50)
                )
            return 0

        async def match_job(self, user, job, *, force: bool = False):
            return repo.rows_by_key.setdefault(
                (user.id, job.id), make_match(job, user_id=user.id, score=77, company_score=50)
            )

        async def record_feedback(self, user, job, feedback):
            row = await self.match_job(user, job)
            row.feedback = feedback
            return row

    signals, signal_repo = make_signal_service()
    saved = FakeSaved()
    applications = FakeApplicationRepository()

    app.dependency_overrides[get_job_match_repository] = lambda: repo
    app.dependency_overrides[get_ranking_service] = lambda: RankingService(
        repo, jobs=FakeJobsByScore(repo.rows), signals=signals  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_matching_service] = lambda: Matching()
    app.dependency_overrides[get_job_repository] = lambda: FakeJobsRepo(jobs)
    app.dependency_overrides[get_preference_signal_service] = lambda: signals
    app.dependency_overrides[get_saved_job_repository] = lambda: saved
    app.dependency_overrides[get_application_repository] = lambda: applications
    app.dependency_overrides[get_application_service] = lambda: ApplicationService(
        applications, signals=signals  # type: ignore[arg-type]
    )
    yield signal_repo, applications
    for dep in (
        get_job_match_repository,
        get_ranking_service,
        get_matching_service,
        get_job_repository,
        get_preference_signal_service,
        get_saved_job_repository,
        get_application_repository,
        get_application_service,
    ):
        app.dependency_overrides.pop(dep, None)


async def _login(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    payload = {"email": email, "password": "password123", "name": "Test User"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": payload["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_auth_required(auth_client: AuthFixture, ranking_overrides) -> None:
    client, _, _ = auth_client
    assert (await client.get("/api/v1/preferences")).status_code == 401
    assert (await client.delete("/api/v1/preferences")).status_code == 401
    assert (await client.post("/api/v1/jobs/j-acme/hide", json={"scope": "company"})).status_code == 401


async def test_signals_flow_reranks_hides_and_resets(auth_client: AuthFixture, ranking_overrides) -> None:
    client, _, _ = auth_client
    signal_repo, _ = ranking_overrides
    headers = await _login(client)

    baseline = await client.get("/api/v1/jobs/recommended", headers=headers)
    assert baseline.status_code == 200
    assert {item["ranking"]["finalScore"] for item in baseline.json()["items"]} == {77.0}

    # Save + like Acme's backend job → Acme backend roles rank higher.
    assert (await client.post("/api/v1/jobs/j-acme/save", headers=headers)).status_code == 200
    fb = await client.post("/api/v1/jobs/j-acme/feedback", json={"feedback": "positive"}, headers=headers)
    assert fb.status_code == 200 and fb.json()["feedback"] == "POSITIVE"  # contract unchanged
    kinds = sorted(str(r.kind) for r in signal_repo.rows.values())
    assert kinds == ["LIKE", "SAVE"]

    recommended = (await client.get("/api/v1/jobs/recommended", headers=headers)).json()
    by_id = {item["job"]["id"]: item for item in recommended["items"]}
    assert by_id["j-acme"]["ranking"]["finalScore"] > by_id["j-zed"]["ranking"]["finalScore"]
    assert by_id["j-acme"]["ranking"]["feedbackScore"] == 5.0
    assert any("roles like" in e for e in by_id["j-acme"]["ranking"]["explanations"])
    # Globex shares the role → also boosted, but less (no company/feedback part).
    assert by_id["j-globex"]["ranking"]["finalScore"] > 77
    assert recommended["items"][0]["job"]["id"] == "j-acme"
    assert by_id["j-acme"]["job"]["ranking"]["finalScore"] == by_id["j-acme"]["ranking"]["finalScore"]

    # Browse view is re-ordered too and carries ranking.
    browse = (await client.get("/api/v1/jobs?sort=score", headers=headers)).json()
    assert browse["items"][0]["id"] == "j-acme" and browse["items"][0]["ranking"] is not None
    assert browse["total"] == 3

    # Hide Globex; it leaves recommendations but stays in the browse view.
    hidden = await client.post("/api/v1/jobs/j-globex/hide", json={"scope": "company"}, headers=headers)
    assert hidden.status_code == 200
    assert [h["label"] for h in hidden.json()["hiddenCompanies"]] == ["Globex"]
    ids = [item["job"]["id"] for item in (await client.get("/api/v1/jobs/recommended", headers=headers)).json()["items"]]
    assert "j-globex" not in ids
    browse_ids = [item["id"] for item in (await client.get("/api/v1/jobs?sort=score", headers=headers)).json()["items"]]
    assert "j-globex" in browse_ids

    prefs = (await client.get("/api/v1/preferences", headers=headers)).json()
    assert prefs["signalCount"] == 3
    assert prefs["preferredRoles"][0]["key"] == "backend engineer"
    assert prefs["preferredCompanies"][0]["label"] == "Acme"
    signal_id = prefs["hiddenCompanies"][0]["signalId"]

    # Un-hide: another user cannot, the owner can.
    other = await _login(client, "other@example.com")
    assert (await client.delete(f"/api/v1/preferences/signals/{signal_id}", headers=other)).status_code == 404
    assert (await client.delete(f"/api/v1/preferences/signals/{signal_id}", headers=headers)).status_code == 204
    ids = [item["job"]["id"] for item in (await client.get("/api/v1/jobs/recommended", headers=headers)).json()["items"]]
    assert "j-globex" in ids

    # Unsave removes the SAVE signal only.
    assert (await client.delete("/api/v1/jobs/j-acme/save", headers=headers)).status_code == 200
    assert sorted(str(r.kind) for r in signal_repo.rows.values()) == ["LIKE"]

    # Reset forgets everything learned; the recommended order returns to base.
    assert (await client.delete("/api/v1/preferences", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/preferences", headers=headers)).json()["signalCount"] == 0
    after = (await client.get("/api/v1/jobs/recommended", headers=headers)).json()
    acme_after = next(i for i in after["items"] if i["job"]["id"] == "j-acme")
    assert acme_after["ranking"]["preferenceScore"] == 0
    assert acme_after["ranking"]["feedbackScore"] == 5.0  # match.feedback is untouched by reset

    bad = await client.post("/api/v1/jobs/j-acme/hide", json={"scope": "everything"}, headers=headers)
    assert bad.status_code == 422
    assert (await client.post("/api/v1/jobs/nope/hide", json={"scope": "role"}, headers=headers)).status_code == 404


async def test_apply_records_signal_and_excludes_from_recommendations(auth_client: AuthFixture, ranking_overrides) -> None:
    client, _, _ = auth_client
    signal_repo, _applications = ranking_overrides
    headers = await _login(client)
    await client.get("/api/v1/jobs/recommended", headers=headers)  # seeds matches

    tracked = await client.post("/api/v1/applications", json={"jobId": "j-zed"}, headers=headers)
    app_id = tracked.json()["id"]
    moved = await client.post(f"/api/v1/applications/{app_id}/status", json={"status": "APPLIED"}, headers=headers)
    assert moved.status_code == 200 and moved.json()["appliedAt"] is not None
    assert [str(r.kind) for r in signal_repo.rows.values()] == ["APPLY"]
    # The tracker's job row comes from make_job_row (title "Backend Engineer").
    assert next(iter(signal_repo.rows.values())).roleKey == "backend engineer"

    # Moving to INTERVIEW later doesn't add a second APPLY signal.
    await client.post(f"/api/v1/applications/{app_id}/status", json={"status": "INTERVIEW"}, headers=headers)
    assert len(signal_repo.rows) == 1

    # Created straight into APPLIED also stamps appliedAt and teaches.
    created = await client.post("/api/v1/applications", json={"jobId": "j-globex", "status": "APPLIED"}, headers=headers)
    assert created.status_code == 200 and created.json()["appliedAt"] is not None
    assert len(signal_repo.rows) == 2
