# camelCase wire contract, mirrored by the frontend zod schemas.
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.db.generated.models import Notification
from app.models import NotificationChannel, NotificationStatus, NotificationType


class NotificationOut(BaseModel):
    id: str
    channel: NotificationChannel
    type: NotificationType
    status: NotificationStatus
    subject: str | None
    body: str | None
    payload: dict[str, Any] | None
    readAt: datetime | None
    createdAt: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    limit: int
    offset: int


class UnreadCountOut(BaseModel):
    unread: int


class ChannelStateOut(BaseModel):
    available: bool  # env flag + credentials (server side)
    enabled: bool  # the user's own toggle


class ChannelsOut(BaseModel):
    inApp: ChannelStateOut
    email: ChannelStateOut
    telegram: ChannelStateOut


class DigestPreviewOut(BaseModel):
    date: str
    subject: str
    body: str
    items: list[dict[str, Any]]
    empty: bool = False


def notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        channel=row.channel,
        type=row.type,
        status=row.status,
        subject=row.subject,
        body=row.body,
        payload=row.payload if isinstance(row.payload, dict) else None,
        readAt=row.readAt,
        createdAt=row.createdAt,
    )
