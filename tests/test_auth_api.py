from httpx import AsyncClient

from tests.fakes import FakeDB, FakeRedis

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}
LOGIN = {"email": "user@example.com", "password": "password123"}

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]


async def test_register_creates_user_and_profile(auth_client: AuthFixture) -> None:
    client, db, _ = auth_client

    response = await client.post("/api/v1/auth/register", json=REGISTER)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["name"] == "Test User"
    assert "passwordHash" not in body
    assert len(db.profiles) == 1  # empty profile created alongside the user


async def test_register_duplicate_email_conflicts(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    await client.post("/api/v1/auth/register", json=REGISTER)

    response = await client.post("/api/v1/auth/register", json=REGISTER)

    assert response.status_code == 409
    assert response.json()["error_code"] == "email_taken"


async def test_register_rejects_weak_password(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client

    response = await client.post(
        "/api/v1/auth/register", json={"email": "a@b.co", "password": "short"}
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"


async def test_login_returns_token_and_refresh_cookie(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    await client.post("/api/v1/auth/register", json=REGISTER)

    response = await client.post("/api/v1/auth/login", json=LOGIN)

    assert response.status_code == 200
    assert response.json()["accessToken"]
    assert response.json()["user"]["email"] == "user@example.com"
    set_cookie = response.headers["set-cookie"]
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie


async def test_login_failures_are_indistinguishable(auth_client: AuthFixture) -> None:
    """Wrong password, unknown email, malformed email, and disabled account
    must all produce byte-identical invalid_credentials responses — no user
    enumeration."""
    client, db, _ = auth_client
    await client.post("/api/v1/auth/register", json=REGISTER)
    disabled = await client.post(
        "/api/v1/auth/register", json={**REGISTER, "email": "off@example.com"}
    )
    assert disabled.status_code == 201
    # Disable the second account directly in the fake store.
    for user in db.users.values():
        if user.email == "off@example.com":
            user.isActive = False

    attempts = [
        {"email": "user@example.com", "password": "wrong-password"},  # wrong password
        {"email": "nobody@example.com", "password": "password123"},  # unknown email
        {"email": "not-an-email", "password": "password123"},  # malformed email
        {"email": "off@example.com", "password": "password123"},  # disabled account
    ]
    bodies = []
    for attempt in attempts:
        response = await client.post("/api/v1/auth/login", json=attempt)
        assert response.status_code == 401
        bodies.append(response.json())

    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["error_code"] == "invalid_credentials"


async def test_me_requires_token(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client

    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401


async def test_me_returns_current_user(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    await client.post("/api/v1/auth/register", json=REGISTER)
    login = await client.post("/api/v1/auth/login", json=LOGIN)
    token = login.json()["accessToken"]

    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "user@example.com"
    assert response.json()["profile"] is not None


async def test_refresh_rotates_token(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client
    await client.post("/api/v1/auth/register", json=REGISTER)
    await client.post("/api/v1/auth/login", json=LOGIN)
    old_refresh = client.cookies.get("refresh_token", path="/api/v1/auth")

    first = await client.post("/api/v1/auth/refresh")
    assert first.status_code == 200
    assert first.json()["accessToken"]

    # Replaying the pre-rotation token must fail: it was revoked on use.
    client.cookies.set("refresh_token", old_refresh, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401


async def test_refresh_without_cookie_unauthorized(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401


async def test_logout_revokes_refresh_token(auth_client: AuthFixture) -> None:
    client, _, fake_redis = auth_client
    await client.post("/api/v1/auth/register", json=REGISTER)
    await client.post("/api/v1/auth/login", json=LOGIN)
    assert any(key.startswith("refresh:") for key in fake_redis.store)

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert not any(key.startswith("refresh:") for key in fake_redis.store)

    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


async def test_auth_endpoints_rate_limited(auth_client: AuthFixture) -> None:
    client, _, _ = auth_client

    last = None
    for _ in range(11):  # limit is 10/minute per IP
        last = await client.post(
            "/api/v1/auth/login", json={"email": "x@y.co", "password": "whatever123"}
        )
    assert last is not None
    assert last.status_code == 429
    assert last.json()["error_code"] == "rate_limited"
