from datetime import UTC, datetime
from typing import Any

from app.db.generated import Json
from app.db.generated.errors import UniqueViolationError
from app.db.generated.models import Notification
from app.models import NotificationChannel, NotificationStatus, NotificationType
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
        try:
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
        except UniqueViolationError:
            # Lost the race with a concurrent digest run (arq retry or a second
            # worker): the unique key did its job, return the winner's row.
            existing = await self._prisma.notification.find_unique(
                where={"dedupeKey": dedupe_key}
            )
            assert existing is not None
            return existing, False
        return created, True

    async def count_since(self, since: datetime) -> int:
        return await self._prisma.notification.count(where={"createdAt": {"gte": since}})

    async def get_by_dedupe_key(self, dedupe_key: str) -> Notification | None:
        return await self._prisma.notification.find_unique(where={"dedupeKey": dedupe_key})

    async def list_in_app_for_user(
        self, user_id: str, *, unread_only: bool, limit: int, offset: int
    ) -> tuple[list[Notification], int]:
        where: dict[str, Any] = {
            "userId": user_id,
            "channel": NotificationChannel.IN_APP,
        }
        if unread_only:
            where["readAt"] = None
        rows = await self._prisma.notification.find_many(
            where=where,
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
        )
        total = await self._prisma.notification.count(where=where)
        return rows, total

    async def unread_count(self, user_id: str) -> int:
        return await self._prisma.notification.count(
            where={
                "userId": user_id,
                "channel": NotificationChannel.IN_APP,
                "readAt": None,
            }
        )

    async def mark_read(self, notification_id: str, user_id: str) -> Notification | None:
        row = await self._prisma.notification.find_unique(where={"id": notification_id})
        if row is None or row.userId != user_id:
            return None
        if row.readAt is not None:
            return row
        return await self._prisma.notification.update(
            where={"id": notification_id}, data={"readAt": datetime.now(UTC)}
        )

    async def mark_all_read(self, user_id: str) -> int:
        return await self._prisma.notification.update_many(
            where={
                "userId": user_id,
                "channel": NotificationChannel.IN_APP,
                "readAt": None,
            },
            data={"readAt": datetime.now(UTC)},
        )

    async def mark_sent(self, notification_id: str) -> Notification:
        return await self._prisma.notification.update(
            where={"id": notification_id},
            data={
                "status": NotificationStatus.SENT,  # type: ignore[typeddict-item]
                "sentAt": datetime.now(UTC),
                "errorMessage": None,
            },
        )

    async def mark_failed(self, notification_id: str, error: str) -> Notification:
        return await self._prisma.notification.update(
            where={"id": notification_id},
            data={
                "status": NotificationStatus.FAILED,  # type: ignore[typeddict-item]
                "errorMessage": error[:500],
            },
        )
