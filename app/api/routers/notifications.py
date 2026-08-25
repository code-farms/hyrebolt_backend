from datetime import UTC, datetime

from fastapi import APIRouter, Query

from app.api.deps import (
    CurrentUserDep,
    DailyDigestServiceDep,
    NotificationRepositoryDep,
    ProfileRepositoryDep,
    SettingsDep,
)
from app.core.exceptions import NotFoundError
from app.core.http import get_shared_http_client
from app.notifications import EmailProvider, TelegramProvider
from app.schemas.notification import (
    ChannelsOut,
    ChannelStateOut,
    DigestPreviewOut,
    NotificationListOut,
    NotificationOut,
    UnreadCountOut,
    notification_out,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    user: CurrentUserDep,
    notifications: NotificationRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    unreadOnly: bool = Query(default=False),
) -> NotificationListOut:
    rows, total = await notifications.list_in_app_for_user(
        user.id, unread_only=unreadOnly, limit=limit, offset=offset
    )
    return NotificationListOut(
        items=[notification_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    user: CurrentUserDep, notifications: NotificationRepositoryDep
) -> UnreadCountOut:
    return UnreadCountOut(unread=await notifications.unread_count(user.id))


@router.get("/channels", response_model=ChannelsOut)
async def channels(
    user: CurrentUserDep,
    profiles: ProfileRepositoryDep,
    settings: SettingsDep,
) -> ChannelsOut:
    profile = await profiles.get_by_user_id(user.id)
    email_available = EmailProvider(settings).is_configured()
    telegram_available = TelegramProvider(settings, get_shared_http_client()).is_configured()
    return ChannelsOut(
        inApp=ChannelStateOut(available=True, enabled=True),  # always on
        email=ChannelStateOut(
            available=email_available,
            enabled=bool(profile.emailEnabled) if profile else True,
        ),
        telegram=ChannelStateOut(
            available=telegram_available,
            enabled=bool(profile.telegramEnabled) if profile else False,
        ),
    )


@router.get("/digest/preview", response_model=DigestPreviewOut)
async def digest_preview(
    user: CurrentUserDep,
    profiles: ProfileRepositoryDep,
    digest_service: DailyDigestServiceDep,
) -> DigestPreviewOut:
    """Builds today's digest live for the caller — nothing is stored or sent."""
    profile = await profiles.get_by_user_id(user.id)
    if profile is None:
        profile = await profiles.upsert_for_user(user.id, {})
    today = datetime.now(UTC).date()
    digest = await digest_service.build_digest(user, profile, today)
    if digest is None:
        return DigestPreviewOut(
            date=today.isoformat(),
            subject="Your daily job digest",
            body="No matches above your threshold today.",
            items=[],
            empty=True,
        )
    return DigestPreviewOut(
        date=digest.date,
        subject=digest.subject,
        body=digest.body,
        items=digest.payload()["items"],
    )


@router.post("/read-all", response_model=UnreadCountOut)
async def read_all(
    user: CurrentUserDep, notifications: NotificationRepositoryDep
) -> UnreadCountOut:
    await notifications.mark_all_read(user.id)
    return UnreadCountOut(unread=0)


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: str,
    user: CurrentUserDep,
    notifications: NotificationRepositoryDep,
) -> NotificationOut:
    row = await notifications.mark_read(notification_id, user.id)
    if row is None:
        raise NotFoundError("Notification not found.")
    return notification_out(row)
