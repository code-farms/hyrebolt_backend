import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from app.api.deps import (
    get_daily_digest_service,
    get_notification_repository,
    get_settings,
)
from app.main import app
from app.models import NotificationChannel, NotificationStatus, NotificationType
from tests.fakes import FakeDB, FakeRedis

AuthFixture = tuple[AsyncClient, FakeDB, FakeRedis]

REGISTER = {"email": "user@example.com", "password": "password123", "name": "Test User"}


@dataclass
class Row:
    id: str
    userId: str
    channel: NotificationChannel = NotificationChannel.IN_APP
    type: NotificationType = NotificationType.DAILY_DIGEST
    status: NotificationStatus = NotificationStatus.PENDING
    subject: str | None = "Digest"
    body: str | None = "Body"
    payload: dict[str, Any] | None = None
    readAt: datetime | None = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeNotificationRepo:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    def seed(self, user_id: str, count: int, *, read: int = 0) -> list[Row]:
        created = []
        for index in range(count):
            row = Row(id=uuid.uuid4().hex, userId=user_id)
            if index < read:
                row.readAt = datetime.now(UTC)
            self.rows[row.id] = row
            created.append(row)
        return created

    async def list_in_app_for_user(self, user_id, *, unread_only, limit, offset):
        rows = [
            r
            for r in self.rows.values()
            if r.userId == user_id and (not unread_only or r.readAt is None)
        ]
        rows.sort(key=lambda r: r.createdAt, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def unread_count(self, user_id):
        return sum(1 for r in self.rows.values() if r.userId == user_id and r.readAt is None)

    async def mark_read(self, notification_id, user_id):
        row = self.rows.get(notification_id)
        if row is None or row.userId != user_id:
            return None
        row.readAt = row.readAt or datetime.now(UTC)
        return row

    async def mark_all_read(self, user_id):
        for row in self.rows.values():
            if row.userId == user_id and row.readAt is None:
                row.readAt = datetime.now(UTC)
        return 0


class StubDigestService:
    async def build_digest(self, user, profile, run_date):
        return None  # preview empty-state path


@pytest.fixture
def notif_overrides():
    repo = FakeNotificationRepo()
    app.dependency_overrides[get_notification_repository] = lambda: repo
    app.dependency_overrides[get_daily_digest_service] = lambda: StubDigestService()
    yield repo
    app.dependency_overrides.pop(get_notification_repository, None)
    app.dependency_overrides.pop(get_daily_digest_service, None)


async def _login(client: AsyncClient) -> tuple[dict[str, str], str]:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
    )
    body = response.json()
    return {"Authorization": f"Bearer {body['accessToken']}"}, body["user"]["id"]


async def test_endpoints_require_auth(auth_client: AuthFixture, notif_overrides) -> None:
    client, _, _ = auth_client
    for path in (
        "/api/v1/notifications",
        "/api/v1/notifications/unread-count",
        "/api/v1/notifications/channels",
        "/api/v1/notifications/digest/preview",
    ):
        assert (await client.get(path)).status_code == 401


async def test_list_unread_and_mark_read_flow(auth_client: AuthFixture, notif_overrides) -> None:
    client, _, _ = auth_client
    repo: FakeNotificationRepo = notif_overrides
    headers, user_id = await _login(client)
    rows = repo.seed(user_id, 3, read=1)
    repo.seed("someone-else", 2)  # never visible

    listing = await client.get("/api/v1/notifications?limit=10", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 3

    unread = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert unread.json() == {"unread": 2}

    unread_only = await client.get("/api/v1/notifications?unreadOnly=true", headers=headers)
    assert unread_only.json()["total"] == 2

    target = next(r for r in rows if r.readAt is None)
    marked = await client.post(f"/api/v1/notifications/{target.id}/read", headers=headers)
    assert marked.status_code == 200
    assert marked.json()["readAt"] is not None

    all_read = await client.post("/api/v1/notifications/read-all", headers=headers)
    assert all_read.json() == {"unread": 0}
    assert (await client.get("/api/v1/notifications/unread-count", headers=headers)).json() == {
        "unread": 0
    }


async def test_mark_read_foreign_or_missing_404(auth_client: AuthFixture, notif_overrides) -> None:
    client, _, _ = auth_client
    repo: FakeNotificationRepo = notif_overrides
    headers, _ = await _login(client)
    foreign = repo.seed("someone-else", 1)[0]

    assert (
        await client.post(f"/api/v1/notifications/{foreign.id}/read", headers=headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/notifications/missing/read", headers=headers)
    ).status_code == 404


async def test_preview_empty_state(auth_client: AuthFixture, notif_overrides) -> None:
    client, _, _ = auth_client
    headers, _ = await _login(client)

    response = await client.get("/api/v1/notifications/digest/preview", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["empty"] is True
    assert body["items"] == []


async def test_channels_reflect_env_flags(auth_client: AuthFixture, notif_overrides) -> None:
    client, _, _ = auth_client
    headers, _ = await _login(client)

    # Pin every channel flag so the test does not depend on the developer's
    # .env (which may have Telegram enabled with a real bot token).
    all_off = get_settings().model_copy(
        update={
            "email_notifications_enabled": False,
            "telegram_notifications_enabled": False,
            "telegram_bot_token": None,
        }
    )
    email_on = all_off.model_copy(
        update={
            "email_notifications_enabled": True,
            "smtp_host": "smtp.test",
            "smtp_from_address": "agent@test",
        }
    )
    try:
        app.dependency_overrides[get_settings] = lambda: all_off
        default = await client.get("/api/v1/notifications/channels", headers=headers)
        body = default.json()
        assert body["inApp"] == {"available": True, "enabled": True}
        assert body["email"]["available"] is False
        assert body["telegram"]["available"] is False

        app.dependency_overrides[get_settings] = lambda: email_on
        enabled = await client.get("/api/v1/notifications/channels", headers=headers)
        assert enabled.json()["email"]["available"] is True
        assert enabled.json()["telegram"]["available"] is False
    finally:
        app.dependency_overrides.pop(get_settings, None)
