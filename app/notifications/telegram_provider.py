"""Telegram provider via the official Bot API, using the shared httpx client.
The user's chat id comes from their profile (set in Settings UI)."""

import httpx

from app.core.config import Settings
from app.db.generated.models import Notification, User, UserProfile
from app.models import NotificationChannel
from app.notifications.base import NotificationProvider, NotificationSendError

TELEGRAM_API = "https://api.telegram.org"


class TelegramProvider(NotificationProvider):
    channel = NotificationChannel.TELEGRAM

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def is_configured(self) -> bool:
        return bool(
            self._settings.telegram_notifications_enabled
            and self._settings.telegram_bot_token
        )

    async def send(
        self, notification: Notification, user: User, profile: UserProfile
    ) -> None:
        if not profile.telegramChatId:
            raise NotificationSendError("no telegram chat id configured on the profile")
        text = f"{notification.subject}\n\n{notification.body or ''}".strip()
        try:
            response = await self._client.post(
                f"{TELEGRAM_API}/bot{self._settings.telegram_bot_token}/sendMessage",
                json={"chat_id": profile.telegramChatId, "text": text},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise NotificationSendError(f"telegram network error: {exc}") from exc
        if response.status_code >= 400:
            raise NotificationSendError(
                f"telegram rejected the message ({response.status_code})"
            )
