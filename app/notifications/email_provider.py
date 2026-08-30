"""SMTP email provider. Uses stdlib smtplib inside asyncio.to_thread — no new
dependency; the blocking transport is injectable so tests never open sockets."""

import asyncio
import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from app.core.config import APP_NAME, Settings
from app.db.generated.models import Notification, User, UserProfile
from app.models import NotificationChannel
from app.notifications.base import NotificationProvider, NotificationSendError

Transport = Callable[[EmailMessage], None]


class EmailProvider(NotificationProvider):
    channel = NotificationChannel.EMAIL

    def __init__(self, settings: Settings, transport: Transport | None = None) -> None:
        self._settings = settings
        self._transport = transport or self._smtp_send

    def is_configured(self) -> bool:
        s = self._settings
        return bool(
            s.email_notifications_enabled and s.smtp_host and s.smtp_from_address
        )

    async def send(
        self, notification: Notification, user: User, profile: UserProfile
    ) -> None:
        message = EmailMessage()
        message["From"] = self._settings.smtp_from_address
        message["To"] = user.email
        message["Subject"] = notification.subject or f"{APP_NAME} notification"
        message.set_content(notification.body or "")
        try:
            await asyncio.to_thread(self._transport, message)
        except Exception as exc:
            raise NotificationSendError(f"email send failed: {exc}") from exc

    def _smtp_send(self, message: EmailMessage) -> None:
        s = self._settings
        assert s.smtp_host is not None
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(message)
