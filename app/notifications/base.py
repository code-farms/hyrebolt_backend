from abc import ABC, abstractmethod

from app.db.generated.models import Notification, User, UserProfile
from app.models import NotificationChannel


class NotificationSendError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotificationProvider(ABC):
    channel: NotificationChannel

    @abstractmethod
    def is_configured(self) -> bool:
        """Env flag on AND credentials present."""

    @abstractmethod
    async def send(
        self, notification: Notification, user: User, profile: UserProfile
    ) -> None:
        """Deliver one notification; raises NotificationSendError on failure."""
