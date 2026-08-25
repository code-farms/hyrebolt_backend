from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError
from app.models import ApplicationStatus
from app.services.application_service import ApplicationService
from tests.applications.fakes import FakeApplicationRepository

USER = SimpleNamespace(id="u1")
OTHER = SimpleNamespace(id="u2")


def make_service() -> tuple[ApplicationService, FakeApplicationRepository]:
    repo = FakeApplicationRepository()
    return ApplicationService(repo), repo  # type: ignore[arg-type]


async def test_track_job_is_idempotent_and_seeds_timeline() -> None:
    service, repo = make_service()

    first = await service.track_job(USER, "j1")  # type: ignore[arg-type]
    second = await service.track_job(USER, "j1")  # type: ignore[arg-type]

    assert first.id == second.id
    assert len(repo.rows) == 1
    assert [e.title for e in first.events] == ["Saved"]
    assert first.status == ApplicationStatus.SAVED


async def test_status_transition_appends_event_and_stamps_applied_at() -> None:
    service, _ = make_service()
    application = await service.track_job(USER, "j1")  # type: ignore[arg-type]

    applied = await service.update_status(
        USER, application.id, ApplicationStatus.APPLIED, note="via referral"  # type: ignore[arg-type]
    )

    assert applied.status == ApplicationStatus.APPLIED
    assert applied.appliedAt is not None
    first_applied_at = applied.appliedAt
    assert applied.events[-1].title == "Moved to Applied"
    assert applied.events[-1].notes == "via referral"

    # Moving away and back must NOT overwrite the original appliedAt.
    await service.update_status(USER, application.id, ApplicationStatus.INTERVIEW)  # type: ignore[arg-type]
    back = await service.update_status(USER, application.id, ApplicationStatus.APPLIED)  # type: ignore[arg-type]
    assert back.appliedAt == first_applied_at


async def test_same_status_is_a_no_op() -> None:
    service, _ = make_service()
    application = await service.track_job(USER, "j1")  # type: ignore[arg-type]

    unchanged = await service.update_status(USER, application.id, ApplicationStatus.SAVED)  # type: ignore[arg-type]

    assert len(unchanged.events) == 1  # only the initial "Saved" event


async def test_details_partial_update() -> None:
    service, _ = make_service()
    application = await service.track_job(USER, "j1")  # type: ignore[arg-type]

    updated = await service.update_details(
        USER, application.id, {"recruiterName": "Priya", "notes": "spoke on phone"}  # type: ignore[arg-type]
    )
    assert updated.recruiterName == "Priya"
    assert updated.notes == "spoke on phone"

    again = await service.update_details(USER, application.id, {"notes": "updated"})  # type: ignore[arg-type]
    assert again.recruiterName == "Priya"  # untouched
    assert again.notes == "updated"


async def test_manual_events() -> None:
    service, _ = make_service()
    application = await service.track_job(USER, "j1")  # type: ignore[arg-type]

    updated = await service.add_event(
        USER, application.id, title="Round 2 interview", notes="system design"  # type: ignore[arg-type]
    )

    assert updated.events[-1].title == "Round 2 interview"
    assert updated.events[-1].status is None


async def test_foreign_application_is_404() -> None:
    service, _ = make_service()
    application = await service.track_job(USER, "j1")  # type: ignore[arg-type]

    with pytest.raises(NotFoundError):
        await service.update_status(OTHER, application.id, ApplicationStatus.APPLIED)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.get(OTHER, application.id)  # type: ignore[arg-type]


async def test_stats_math() -> None:
    service, _ = make_service()
    ids = []
    for i in range(5):
        app = await service.track_job(USER, f"j{i}")  # type: ignore[arg-type]
        ids.append(app.id)
    await service.update_status(USER, ids[0], ApplicationStatus.APPLIED)  # type: ignore[arg-type]
    await service.update_status(USER, ids[1], ApplicationStatus.INTERVIEW)  # type: ignore[arg-type]
    await service.update_status(USER, ids[2], ApplicationStatus.OFFER)  # type: ignore[arg-type]
    await service.update_status(USER, ids[3], ApplicationStatus.REJECTED)  # type: ignore[arg-type]

    stats = await service.stats(USER)  # type: ignore[arg-type]

    assert stats["total"] == 5
    assert stats["interviews"] == 1
    assert stats["offers"] == 1
    assert stats["rejected"] == 1
    assert stats["rejectionRate"] == 20.0
    assert stats["conversionRate"] == 20.0
    assert stats["byStatus"]["SAVED"] == 1


async def test_stats_zero_total() -> None:
    service, _ = make_service()
    stats = await service.stats(USER)  # type: ignore[arg-type]
    assert stats == {
        "total": 0,
        "byStatus": {s.value: 0 for s in ApplicationStatus},
        "interviews": 0,
        "offers": 0,
        "rejected": 0,
        "rejectionRate": 0.0,
        "conversionRate": 0.0,
    }
