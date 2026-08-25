"""Pluggable notification providers (Phase 10). Email/Telegram are env-gated;
the in-app channel needs no provider (rows land in the bell via the API)."""

from app.notifications.base import NotificationProvider, NotificationSendError
from app.notifications.email_provider import EmailProvider
from app.notifications.registry import build_providers
from app.notifications.telegram_provider import TelegramProvider

__all__ = [
    "EmailProvider",
    "NotificationProvider",
    "NotificationSendError",
    "TelegramProvider",
    "build_providers",
]
