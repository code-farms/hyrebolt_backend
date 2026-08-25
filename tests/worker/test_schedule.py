from datetime import UTC, datetime

import pytest

from app.worker.schedule import compute_utc_cron, next_scheduled_run_utc, parse_daily_time


def test_ist_conversion() -> None:
    assert compute_utc_cron("08:00", "Asia/Kolkata") == (2, 30)


def test_conversion_wrapping_to_previous_utc_day() -> None:
    assert compute_utc_cron("00:15", "Asia/Kolkata") == (18, 45)


def test_utc_passthrough() -> None:
    assert compute_utc_cron("09:30", "UTC") == (9, 30)


def test_invalid_time_strings() -> None:
    with pytest.raises(ValueError):
        parse_daily_time("8am")
    with pytest.raises(ValueError):
        parse_daily_time("25:00")
    with pytest.raises(ValueError):
        parse_daily_time("08:75")


def test_next_run_before_and_after_todays_slot() -> None:
    before = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)  # 06:30 IST, before 08:00
    after = datetime(2026, 8, 25, 5, 0, tzinfo=UTC)  # 10:30 IST, after 08:00

    next_before = next_scheduled_run_utc("08:00", "Asia/Kolkata", now=before)
    next_after = next_scheduled_run_utc("08:00", "Asia/Kolkata", now=after)

    assert next_before == datetime(2026, 8, 25, 2, 30, tzinfo=UTC)
    assert next_after == datetime(2026, 8, 26, 2, 30, tzinfo=UTC)
