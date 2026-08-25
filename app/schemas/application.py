# camelCase wire contract, mirrored by the frontend zod schemas.
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.generated.models import Application, ApplicationEvent
from app.models import ApplicationStatus
from app.schemas.job import JobOut, job_out


class ApplicationEventOut(BaseModel):
    id: str
    title: str
    status: ApplicationStatus | None
    notes: str | None
    occurredAt: datetime


class ApplicationOut(BaseModel):
    id: str
    status: ApplicationStatus
    appliedAt: datetime | None
    notes: str | None
    recruiterName: str | None
    recruiterEmail: str | None
    recruiterPhone: str | None
    job: JobOut
    events: list[ApplicationEventOut]
    createdAt: datetime
    updatedAt: datetime


class ApplicationListOut(BaseModel):
    items: list[ApplicationOut]
    total: int
    limit: int
    offset: int


class ApplicationStatsOut(BaseModel):
    """rejectionRate = rejected/total ·100; conversionRate = offers/total ·100."""

    total: int
    byStatus: dict[str, int]
    interviews: int
    offers: int
    rejected: int
    rejectionRate: float
    conversionRate: float


class TrackJobIn(BaseModel):
    jobId: str
    status: ApplicationStatus = ApplicationStatus.SAVED


class StatusIn(BaseModel):
    status: ApplicationStatus
    note: str | None = Field(default=None, max_length=2000)


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class DetailsIn(BaseModel):
    appliedAt: datetime | None = None
    notes: str | None = Field(default=None, max_length=10000)
    recruiterName: str | None = Field(default=None, max_length=120)
    recruiterEmail: str | None = Field(default=None, max_length=254)
    recruiterPhone: str | None = Field(default=None, max_length=32)

    def to_update(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


def application_out(application: Application) -> ApplicationOut:
    assert application.job is not None
    return ApplicationOut(
        id=application.id,
        status=application.status,
        appliedAt=application.appliedAt,
        notes=application.notes,
        recruiterName=application.recruiterName,
        recruiterEmail=application.recruiterEmail,
        recruiterPhone=application.recruiterPhone,
        job=job_out(application.job),
        events=[_event_out(event) for event in application.events or []],
        createdAt=application.createdAt,
        updatedAt=application.updatedAt,
    )


def _event_out(event: ApplicationEvent) -> ApplicationEventOut:
    return ApplicationEventOut(
        id=event.id,
        title=event.title,
        status=event.status,
        notes=event.notes,
        occurredAt=event.occurredAt,
    )
