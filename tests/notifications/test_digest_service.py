from datetime import date

from app.models import NotificationChannel, NotificationStatus
from app.notifications.base import NotificationProvider, NotificationSendError
from app.services.daily_digest_service import DailyDigestService
from tests.worker.test_tasks import (
    FakeNotifications,
    FakeProfilesRepo,
    FakeRanking,
    make_profile,
    make_user,
    match_row,
)

TODAY = date(2026, 8, 25)
USER = make_user("u1")


class RecordingProvider(NotificationProvider):
    def __init__(self, channel: NotificationChannel, *, fail: bool = False) -> None:
        self.channel = channel
        self.fail = fail
        self.sent: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def send(self, notification, user, profile) -> None:
        if self.fail:
            raise NotificationSendError("provider down")
        self.sent.append(notification["dedupeKey"])


class StatefulFakeNotifications(FakeNotifications):
    """FakeNotifications plus the status transitions the digest service uses."""

    async def create_if_absent(self, *, dedupe_key: str, **kwargs):
        row, created = await super().create_if_absent(dedupe_key=dedupe_key, **kwargs)
        row.setdefault("id", dedupe_key)
        row.setdefault("status", NotificationStatus.PENDING)
        return SimpleNamespaceDict(row), created

    async def mark_sent(self, notification_id: str):
        self.rows[notification_id]["status"] = NotificationStatus.SENT

    async def mark_failed(self, notification_id: str, error: str):
        self.rows[notification_id]["status"] = NotificationStatus.FAILED
        self.rows[notification_id]["errorMessage"] = error


class SimpleNamespaceDict(dict):
    """Dict rows that also allow attribute access (row.id, row.status)."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


def make_digest_service(
    *,
    providers: dict | None = None,
    profile=None,
    rows=None,
) -> tuple[DailyDigestService, StatefulFakeNotifications, FakeRanking]:
    ranking = FakeRanking({"u1": rows if rows is not None else [match_row("j1", 90), match_row("j2", 72)]})
    notifications = StatefulFakeNotifications()
    service = DailyDigestService(
        ranking=ranking,  # type: ignore[arg-type]
        profiles=FakeProfilesRepo({"u1": profile or make_profile(roles=[], locations=[])}),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        providers=providers or {},
    )
    return service, notifications, ranking


async def test_bands_and_item_fields() -> None:
    rows = [match_row("hot", 90), match_row("strong", 75), match_row("maybe", 62)]
    rows[0].whyMatch = "Great overlap"
    rows[0].missingSkills = ["kubernetes"]
    service, _, _ = make_digest_service(rows=rows)

    digest = await service.build_digest(USER, make_profile(roles=[], locations=[]), TODAY)

    assert digest is not None
    assert [item.band for item in digest.items] == ["excellent", "strong", "potential"]
    assert "🔥 Excellent Matches" in digest.body
    assert "🟢 Strong Matches" in digest.body
    assert "🟡 Potential Matches" in digest.body
    assert "Good Morning!" in digest.body
    assert "Why: Great overlap" in digest.body
    assert "Missing: kubernetes" in digest.body
    assert digest.items[0].applyUrl == "https://example.com/hot"


async def test_empty_digest_is_none() -> None:
    service, _, _ = make_digest_service(rows=[])
    assert await service.build_digest(USER, make_profile(roles=[], locations=[]), TODAY) is None


async def test_in_app_always_created_even_with_no_providers() -> None:
    service, notifications, _ = make_digest_service(providers={})

    outcomes = await service.send_for_user(USER, TODAY)

    assert outcomes == {"in_app": "created"}
    assert f"digest:u1:{TODAY.isoformat()}:in_app" in notifications.rows


async def test_email_requires_env_provider_and_user_toggle() -> None:
    provider = RecordingProvider(NotificationChannel.EMAIL)

    # Provider available + user enabled -> sent.
    profile = make_profile(roles=[], locations=[])
    profile.emailEnabled = True
    service, notifications, _ = make_digest_service(
        providers={NotificationChannel.EMAIL: provider}, profile=profile
    )
    outcomes = await service.send_for_user(USER, TODAY)
    assert outcomes["email"] == "sent"
    assert notifications.rows[f"digest:u1:{TODAY.isoformat()}:email"]["status"] == NotificationStatus.SENT

    # Provider available but user disabled -> nothing.
    disabled_profile = make_profile(roles=[], locations=[])
    disabled_profile.emailEnabled = False
    service2, notifications2, _ = make_digest_service(
        providers={NotificationChannel.EMAIL: provider}, profile=disabled_profile
    )
    outcomes2 = await service2.send_for_user(USER, TODAY)
    assert "email" not in outcomes2
    assert f"digest:u1:{TODAY.isoformat()}:email" not in notifications2.rows

    # User enabled but provider env-off (absent) -> nothing.
    service3, _notifications3, _ = make_digest_service(providers={}, profile=profile)
    outcomes3 = await service3.send_for_user(USER, TODAY)
    assert "email" not in outcomes3


async def test_sent_rows_never_resend_failed_rows_retry() -> None:
    provider = RecordingProvider(NotificationChannel.EMAIL)
    profile = make_profile(roles=[], locations=[])
    profile.emailEnabled = True
    service, notifications, _ = make_digest_service(
        providers={NotificationChannel.EMAIL: provider}, profile=profile
    )

    first = await service.send_for_user(USER, TODAY)
    second = await service.send_for_user(USER, TODAY)
    assert first["email"] == "sent"
    assert second["email"] == "deduped"
    assert len(provider.sent) == 1  # never delivered twice

    # FAILED rows are retried on the next run.
    key = f"digest:u1:{TODAY.isoformat()}:email"
    notifications.rows[key]["status"] = NotificationStatus.FAILED
    third = await service.send_for_user(USER, TODAY)
    assert third["email"] == "sent"
    assert len(provider.sent) == 2


async def test_provider_failure_marks_failed_not_raised() -> None:
    provider = RecordingProvider(NotificationChannel.TELEGRAM, fail=True)
    profile = make_profile(roles=[], locations=[])
    profile.telegramEnabled = True
    service, notifications, _ = make_digest_service(
        providers={NotificationChannel.TELEGRAM: provider}, profile=profile
    )

    outcomes = await service.send_for_user(USER, TODAY)

    assert outcomes["telegram"] == "failed"
    key = f"digest:u1:{TODAY.isoformat()}:telegram"
    assert notifications.rows[key]["status"] == NotificationStatus.FAILED
    assert outcomes["in_app"] == "created"  # bell unaffected by provider failure
