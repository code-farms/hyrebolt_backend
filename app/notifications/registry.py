import httpx

from app.core.config import Settings
from app.models import NotificationChannel
from app.notifications.base import NotificationProvider
from app.notifications.email_provider import EmailProvider
from app.notifications.telegram_provider import TelegramProvider


def build_providers(
    settings: Settings, client: httpx.AsyncClient
) -> dict[NotificationChannel, NotificationProvider]:
    """Only configured (env-enabled + credentialed) providers are returned;
    everything else simply doesn't exist at runtime."""
    candidates: list[NotificationProvider] = [
        EmailProvider(settings),
        TelegramProvider(settings, client),
    ]
    return {p.channel: p for p in candidates if p.is_configured()}
