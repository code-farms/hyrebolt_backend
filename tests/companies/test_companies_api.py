import pytest
from httpx import AsyncClient

from app.api.deps import get_company_service
from app.main import app
from tests.companies.fakes import CompanyHarness, make_harness
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

BASE = "/api/v1/companies"


@pytest.fixture
def harness() -> CompanyHarness:  # type: ignore[misc]
    h = make_harness()
    app.dependency_overrides[get_company_service] = lambda: h.service
    yield h
    app.dependency_overrides.pop(get_company_service, None)


async def _login(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    payload = {"email": email, "password": "password123", "name": "Test User"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": payload["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_auth_required(auth_client: AuthFixture, harness: CompanyHarness) -> None:
    client, _, _ = auth_client
    assert (await client.get(BASE)).status_code == 401
    assert (await client.get(f"{BASE}/watchlist")).status_code == 401
    assert (await client.post(f"{BASE}/watchlist", json={"companyName": "Acme"})).status_code == 401


async def test_watchlist_crud_flow(auth_client: AuthFixture, harness: CompanyHarness) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    created = await client.post(
        f"{BASE}/watchlist",
        json={
            "companyName": "Acme",
            "priority": "HIGH",
            "preferredRoles": ["Backend Engineer"],
            "careersUrl": "https://jobs.lever.co/acme",
        },
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["priority"] == "HIGH"
    assert body["company"]["careersUrl"] == "https://jobs.lever.co/acme"
    assert body["company"]["openPositions"] == 0
    assert body["company"]["watchlist"]["id"] == body["id"]

    duplicate = await client.post(
        f"{BASE}/watchlist", json={"companyName": "ACME"}, headers=headers
    )
    assert duplicate.status_code == 409

    # Static route must not be swallowed by /{company_id}.
    listed = await client.get(f"{BASE}/watchlist", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    recent = await client.get(f"{BASE}/watchlist/jobs", headers=headers)
    assert recent.status_code == 200 and recent.json()["items"] == []

    patched = await client.patch(
        f"{BASE}/watchlist/{body['id']}",
        json={"priority": "LOW", "notes": "Talk to Priya"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["priority"] == "LOW"
    assert patched.json()["notes"] == "Talk to Priya"

    other_headers = await _login(client, "other@example.com")
    forbidden = await client.patch(
        f"{BASE}/watchlist/{body['id']}", json={"priority": "HIGH"}, headers=other_headers
    )
    assert forbidden.status_code == 404

    deleted = await client.delete(f"{BASE}/watchlist/{body['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"{BASE}/watchlist", headers=headers)).json()["total"] == 0
    assert harness.matches.stale_calls and harness.matching.rescored


async def test_validation_errors(auth_client: AuthFixture, harness: CompanyHarness) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    both = await client.post(
        f"{BASE}/watchlist", json={"companyId": "c1", "companyName": "Acme"}, headers=headers
    )
    assert both.status_code == 422
    bad_url = await client.post(
        f"{BASE}/watchlist", json={"companyName": "Acme", "careersUrl": "acme"}, headers=headers
    )
    assert bad_url.status_code == 422
    bad_priority = await client.post(
        f"{BASE}/watchlist", json={"companyName": "Acme", "priority": "URGENT"}, headers=headers
    )
    assert bad_priority.status_code == 422


async def test_company_search_detail_jobs_and_metadata(
    auth_client: AuthFixture, harness: CompanyHarness
) -> None:
    client, _, _ = auth_client
    headers = await _login(client)
    acme = harness.companies.seed("Acme", industry="Fintech")
    harness.companies.seed("Globex")
    harness.jobs.add("j1", acme.id)

    search = await client.get(f"{BASE}?q=acm", headers=headers)
    assert search.status_code == 200
    assert [c["name"] for c in search.json()["items"]] == ["Acme"]
    assert search.json()["items"][0]["openPositions"] == 1

    detail = await client.get(f"{BASE}/{acme.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["industry"] == "Fintech"
    assert detail.json()["stage"] is None
    assert detail.json()["watchlist"] is None

    jobs = await client.get(f"{BASE}/{acme.id}/jobs", headers=headers)
    assert jobs.status_code == 200
    assert [j["id"] for j in jobs.json()["items"]] == ["j1"]
    assert jobs.json()["items"][0]["companyId"] == acme.id

    not_watched = await client.patch(
        f"{BASE}/{acme.id}", json={"stage": "Series A"}, headers=headers
    )
    assert not_watched.status_code == 404

    await client.post(f"{BASE}/watchlist", json={"companyId": acme.id}, headers=headers)
    edited = await client.patch(
        f"{BASE}/{acme.id}",
        json={"stage": "Series A", "website": "https://acme.example"},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["stage"] == "Series A"
    assert edited.json()["metadataSource"] == "user"
    assert edited.json()["watchlist"] is not None

    missing = await client.get(f"{BASE}/nope", headers=headers)
    assert missing.status_code == 404
