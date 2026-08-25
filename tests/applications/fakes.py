import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models import ApplicationStatus
from tests.discovery.test_jobs_api import make_job_row


@dataclass
class FakeEvent:
    id: str
    applicationId: str
    title: str
    status: ApplicationStatus | None
    notes: str | None
    occurredAt: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeApplication:
    id: str
    userId: str
    jobId: str
    status: ApplicationStatus
    appliedAt: datetime | None = None
    notes: str | None = None
    recruiterName: str | None = None
    recruiterEmail: str | None = None
    recruiterPhone: str | None = None
    deletedAt: datetime | None = None
    job: Any = None
    events: list[FakeEvent] = field(default_factory=list)
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))
    updatedAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeApplicationRepository:
    def __init__(self) -> None:
        self.rows: dict[str, FakeApplication] = {}

    async def create(self, user_id: str, job_id: str, status: ApplicationStatus):
        row = FakeApplication(
            id=uuid.uuid4().hex,
            userId=user_id,
            jobId=job_id,
            status=status,
            job=make_job_row(job_id),
        )
        self.rows[row.id] = row
        return row

    async def get_by_user_job(self, user_id: str, job_id: str):
        return next(
            (
                r
                for r in self.rows.values()
                if r.userId == user_id and r.jobId == job_id and r.deletedAt is None
            ),
            None,
        )

    async def get_for_user(self, application_id: str, user_id: str):
        row = self.rows.get(application_id)
        if row is None or row.userId != user_id or row.deletedAt is not None:
            return None
        return row

    async def list_for_user(self, user_id: str, *, status=None, limit: int, offset: int):
        rows = [
            r
            for r in self.rows.values()
            if r.userId == user_id
            and r.deletedAt is None
            and (status is None or r.status == status)
        ]
        rows.sort(key=lambda r: r.updatedAt, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def update(self, application_id: str, data: dict[str, Any]):
        row = self.rows[application_id]
        for key, value in data.items():
            setattr(row, key, value)
        row.updatedAt = datetime.now(UTC)
        return row

    async def add_event(
        self, application_id: str, *, title, status=None, notes=None, occurred_at=None
    ):
        event = FakeEvent(
            id=uuid.uuid4().hex,
            applicationId=application_id,
            title=title,
            status=status,
            notes=notes,
        )
        self.rows[application_id].events.append(event)
        return event

    async def count_by_status(self, user_id: str) -> dict[str, int]:
        counts = {status.value: 0 for status in ApplicationStatus}
        for row in self.rows.values():
            if row.userId == user_id and row.deletedAt is None:
                counts[row.status.value] += 1
        return counts

    async def count_for_user(self, user_id: str, *, status=None) -> int:
        return len(
            [
                r
                for r in self.rows.values()
                if r.userId == user_id
                and r.deletedAt is None
                and (status is None or r.status == status)
            ]
        )
