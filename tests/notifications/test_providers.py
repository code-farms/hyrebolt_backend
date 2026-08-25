from email.message import EmailMessage
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import get_settings
from app.models import NotificationChannel
from app.notifications import (
    EmailProvider,
    NotificationSendError,
    TelegramProvider,
    build_providers,
)

USER = SimpleNamespace(id="u1", email="dev@example.com")
NOTIFICATION = SimpleNamespace(subject="Digest", body="Hello!")


def email_settings(**overrides):
    base = {
        "email_notifications_enabled": True,
        "smtp_host": "smtp.test",
        "smtp_from_address": "agent@test",
        "smtp_username": "u",
        "smtp_password": "p",
    }
    base.update(overrides)
    return get_settings().model_copy(update=base)


def test_provider_env_gating() -> None:
    # Flag off => unavailable even with credentials.
    assert not EmailProvider(email_settings(email_notifications_enabled=False)).is_configured()
    # Flag on but no credentials => unavailable.
    assert not EmailProvider(email_settings(smtp_host=None)).is_configured()
    assert EmailProvider(email_settings()).is_configured()

    telegram_off = get_settings().model_copy(
        update={"telegram_notifications_enabled": True, "telegram_bot_token": None}
    )
    telegram_on = get_settings().model_copy(
        update={"telegram_notifications_enabled": True, "telegram_bot_token": "t0k"}
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert not TelegramProvider(telegram_off, client).is_configured()
    assert TelegramProvider(telegram_on, client).is_configured()


def test_build_providers_only_includes_configured() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    none = build_providers(get_settings(), client)  # all env-off by default
    assert none == {}

    email_only = build_providers(email_settings(), client)
    assert set(email_only) == {NotificationChannel.EMAIL}


async def test_email_provider_sends_via_transport() -> None:
    sent: list[EmailMessage] = []
    provider = EmailProvider(email_settings(), transport=sent.append)
    profile = SimpleNamespace(telegramChatId=None)

    await provider.send(NOTIFICATION, USER, profile)  # type: ignore[arg-type]

    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "dev@example.com"
    assert message["From"] == "agent@test"
    assert message["Subject"] == "Digest"
    assert "Hello!" in message.get_content()


async def test_email_transport_failure_is_send_error() -> None:
    def explode(message: EmailMessage) -> None:
        raise ConnectionError("smtp down")

    provider = EmailProvider(email_settings(), transport=explode)
    with pytest.raises(NotificationSendError):
        await provider.send(NOTIFICATION, USER, SimpleNamespace(telegramChatId=None))  # type: ignore[arg-type]


async def test_telegram_provider_request_shape_and_errors() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = request.read()
        return httpx.Response(200, json={"ok": True})

    settings = get_settings().model_copy(
        update={"telegram_notifications_enabled": True, "telegram_bot_token": "t0k"}
    )
    provider = TelegramProvider(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    profile = SimpleNamespace(telegramChatId="12345")

    await provider.send(NOTIFICATION, USER, profile)  # type: ignore[arg-type]
    assert "bott0k/sendMessage" in captured["url"]
    assert b"12345" in captured["json"]

    # Missing chat id -> send error (recorded as FAILED upstream, never raised to the task).
    with pytest.raises(NotificationSendError):
        await provider.send(NOTIFICATION, USER, SimpleNamespace(telegramChatId=None))  # type: ignore[arg-type]

    rejecting = TelegramProvider(
        settings, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    )
    with pytest.raises(NotificationSendError):
        await rejecting.send(NOTIFICATION, USER, profile)  # type: ignore[arg-type]
