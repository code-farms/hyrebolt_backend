from httpx import AsyncClient

from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


async def _login(client: AsyncClient) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_profile_update_roundtrip(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    update = {
        "currentRole": "Backend Engineer",
        "yearsOfExperience": 3.5,
        "targetRoles": ["Backend Engineer", "Platform Engineer"],
        "preferredLocations": ["Bengaluru", "Remote"],
        "remotePreference": "REMOTE",
        "minimumSalary": 2500000,
        "preferredSalary": 3500000,
        "noticePeriodDays": 30,
        "industries": ["SaaS"],
        "preferredCompanies": ["Stripe"],
        "excludedCompanies": ["Acme"],
    }
    put = await client.put("/api/v1/users/me/profile", json=update, headers=headers)
    assert put.status_code == 200
    assert put.json()["currentRole"] == "Backend Engineer"
    assert put.json()["remotePreference"] == "REMOTE"

    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    profile = me.json()["profile"]
    assert profile["targetRoles"] == ["Backend Engineer", "Platform Engineer"]
    assert profile["minimumSalary"] == 2500000


async def test_profile_partial_update_keeps_other_fields(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    headers = await _login(client)
    await client.put(
        "/api/v1/users/me/profile", json={"currentRole": "Backend Engineer"}, headers=headers
    )

    await client.put("/api/v1/users/me/profile", json={"phone": "+91 9999999999"}, headers=headers)

    me = await client.get("/api/v1/users/me", headers=headers)
    profile = me.json()["profile"]
    assert profile["currentRole"] == "Backend Engineer"
    assert profile["phone"] == "+91 9999999999"


async def test_profile_validation_rejects_bad_values(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.put(
        "/api/v1/users/me/profile", json={"yearsOfExperience": -2}, headers=headers
    )

    assert response.status_code == 422


async def test_profile_list_fields_are_bounded(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    too_many = await client.put(
        "/api/v1/users/me/profile",
        json={"targetRoles": [f"role {i}" for i in range(31)]},
        headers=headers,
    )
    too_long = await client.put(
        "/api/v1/users/me/profile", json={"preferredCompanies": ["x" * 121]}, headers=headers
    )
    huge_education = await client.put(
        "/api/v1/users/me/profile", json={"education": {"blob": "e" * 25_000}}, headers=headers
    )
    fine = await client.put(
        "/api/v1/users/me/profile",
        json={"targetRoles": ["Backend Engineer"], "education": [{"degree": "B.Tech"}]},
        headers=headers,
    )

    assert too_many.status_code == 422
    assert too_long.status_code == 422
    assert huge_education.status_code == 422
    assert fine.status_code == 200
    assert fine.json()["targetRoles"] == ["Backend Engineer"]


async def test_skills_replace(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    two = await client.put(
        "/api/v1/users/me/skills",
        json={
            "skills": [
                {"skillName": "Python", "proficiency": "ADVANCED", "yearsOfExperience": 4},
                {"skillName": "React", "proficiency": "INTERMEDIATE", "yearsOfExperience": 2},
            ]
        },
        headers=headers,
    )
    assert two.status_code == 200
    assert {s["skillName"] for s in two.json()} == {"Python", "React"}

    one = await client.put(
        "/api/v1/users/me/skills",
        json={"skills": [{"skillName": "Go", "proficiency": "BEGINNER"}]},
        headers=headers,
    )
    assert one.status_code == 200
    assert [s["skillName"] for s in one.json()] == ["Go"]


async def test_skills_dedupe_by_normalized_name(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    headers = await _login(client)

    response = await client.put(
        "/api/v1/users/me/skills",
        json={
            "skills": [
                {"skillName": "python", "proficiency": "BEGINNER"},
                {"skillName": "Python", "proficiency": "ADVANCED", "yearsOfExperience": 5},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["proficiency"] == "ADVANCED"


async def test_skills_require_auth(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client

    response = await client.put("/api/v1/users/me/skills", json={"skills": []})

    assert response.status_code == 401
