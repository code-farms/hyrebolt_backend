from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.generated.models import Application, User
from app.models import ApplicationStatus, PreferenceSignalKind
from app.repositories import ApplicationRepository
from app.services.preference_signal_service import PreferenceSignalService

logger = get_logger(__name__)

STATUS_LABELS: dict[ApplicationStatus, str] = {
    ApplicationStatus.SAVED: "Saved",
    ApplicationStatus.INTERESTED: "Interested",
    ApplicationStatus.APPLIED: "Applied",
    ApplicationStatus.ASSESSMENT: "Assessment",
    ApplicationStatus.INTERVIEW: "Interview",
    ApplicationStatus.OFFER: "Offer",
    ApplicationStatus.REJECTED: "Rejected",
    ApplicationStatus.WITHDRAWN: "Withdrawn",
}


class ApplicationService:
    def __init__(
        self,
        applications: ApplicationRepository,
        signals: PreferenceSignalService | None = None,
    ) -> None:
        self._applications = applications
        self._signals = signals  # Phase 16: applying is the strongest preference signal

    async def track_job(
        self, user: User, job_id: str, status: ApplicationStatus = ApplicationStatus.SAVED
    ) -> Application:
        """Idempotent: an existing (non-deleted) application is returned as-is."""
        existing = await self._applications.get_by_user_job(user.id, job_id)
        if existing is not None:
            return existing
        application = await self._applications.create(user.id, job_id, status)
        if status == ApplicationStatus.APPLIED:
            # Created straight into APPLIED: stamp the date like a transition would.
            await self._applications.update(application.id, {"appliedAt": datetime.now(UTC)})
        await self._applications.add_event(
            application.id, title=STATUS_LABELS[status], status=status
        )
        logger.info("application_tracked", job_id=job_id, user_id=user.id, status=status)
        refreshed = await self._applications.get_for_user(application.id, user.id)
        assert refreshed is not None
        if status == ApplicationStatus.APPLIED:
            await self._record_apply(user, refreshed)
        return refreshed

    async def get(self, user: User, application_id: str) -> Application:
        return await self._require(user, application_id)

    async def list(
        self,
        user: User,
        *,
        status: ApplicationStatus | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Application], int]:
        return await self._applications.list_for_user(
            user.id, status=status, limit=limit, offset=offset
        )

    async def update_status(
        self,
        user: User,
        application_id: str,
        status: ApplicationStatus,
        note: str | None = None,
    ) -> Application:
        application = await self._require(user, application_id)
        if application.status == status:
            return application
        data: dict[str, Any] = {"status": status}
        # First transition into APPLIED stamps the application date.
        first_apply = status == ApplicationStatus.APPLIED and application.appliedAt is None
        if first_apply:
            data["appliedAt"] = datetime.now(UTC)
        updated = await self._applications.update(application_id, data)
        await self._applications.add_event(
            application_id,
            title=f"Moved to {STATUS_LABELS[status]}",
            status=status,
            notes=note,
        )
        logger.info(
            "application_status_changed",
            application_id=application_id,
            status=str(status),
        )
        refreshed = await self._applications.get_for_user(application_id, user.id)
        if first_apply:
            await self._record_apply(user, refreshed or updated)
        return refreshed or updated

    async def _record_apply(self, user: User, application: Application) -> None:
        job = getattr(application, "job", None)
        if self._signals is None or job is None:
            return
        await self._signals.record(user, job, PreferenceSignalKind.APPLY)

    async def update_details(
        self, user: User, application_id: str, data: dict[str, Any]
    ) -> Application:
        await self._require(user, application_id)
        if not data:
            refreshed = await self._applications.get_for_user(application_id, user.id)
            assert refreshed is not None
            return refreshed
        return await self._applications.update(application_id, data)

    async def add_event(
        self, user: User, application_id: str, *, title: str, notes: str | None = None
    ) -> Application:
        await self._require(user, application_id)
        await self._applications.add_event(application_id, title=title, notes=notes)
        refreshed = await self._applications.get_for_user(application_id, user.id)
        assert refreshed is not None
        return refreshed

    async def stats(self, user: User) -> dict[str, Any]:
        """rejectionRate = rejected/total, conversionRate = offers/total —
        both as percentages over all tracked applications."""
        by_status = await self._applications.count_by_status(user.id)
        total = sum(by_status.values())
        interviews = by_status.get(ApplicationStatus.INTERVIEW.value, 0)
        offers = by_status.get(ApplicationStatus.OFFER.value, 0)
        rejected = by_status.get(ApplicationStatus.REJECTED.value, 0)
        return {
            "total": total,
            "byStatus": by_status,
            "interviews": interviews,
            "offers": offers,
            "rejected": rejected,
            "rejectionRate": round(rejected / total * 100, 1) if total else 0.0,
            "conversionRate": round(offers / total * 100, 1) if total else 0.0,
        }

    async def _require(self, user: User, application_id: str) -> Application:
        application = await self._applications.get_for_user(application_id, user.id)
        if application is None:
            raise NotFoundError("Application not found.")
        return application
