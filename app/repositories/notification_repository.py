from datetime import datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.models import Notification
from app.models import NotificationChannel, NotificationType
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository):
    async def create_if_absent(
        self,
        *,
        dedupe_key: str,
        user_id: str,
        channel: NotificationChannel,
        notification_type: NotificationType,
        subject: str,
        body: str | None,
        payload: dict[str, Any] | None,
    ) -> tuple[Notification, bool]:
        """Idempotent create keyed on the unique dedupeKey: an existing row is
        returned untouched, so a retried digest can never double-notify."""
        existing = await self._prisma.notification.find_unique(
            where={"dedupeKey": dedupe_key}
        )
        if existing is not None:
            return existing, False
        created = await self._prisma.notification.create(
            data={
                "dedupeKey": dedupe_key,
                "userId": user_id,
                "channel": channel,  # type: ignore[typeddict-item]
                "type": notification_type,  # type: ignore[typeddict-item]
                "subject": subject,
                "body": body,
                "payload": Json(payload) if payload is not None else None,
            }
        )
        return created, True

    async def count_since(self, since: datetime) -> int:
        return await self._prisma.notification.count(where={"createdAt": {"gte": since}})
