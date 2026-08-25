"""Timezone-aware schedule math. arq's cron runs on UTC, so the configured
local time (default Asia/Kolkata) is converted at worker startup.

Caveat: the conversion uses today's UTC offset. For fixed-offset zones (IST)
this is exact; for DST zones the fire time can shift by the DST delta until
the worker restarts — acceptable for a daily digest, documented here."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def parse_daily_time(value: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = value.strip().split(":")
        hour, minute = int(hour_str), int(minute_str)
    except ValueError as exc:
        raise ValueError(f"DAILY_SEARCH_TIME must be HH:MM, got {value!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"DAILY_SEARCH_TIME out of range: {value!r}")
    return hour, minute


def compute_utc_cron(
    daily_time: str, timezone: str, *, now: datetime | None = None
) -> tuple[int, int]:
    """The configured local HH:MM expressed as a UTC (hour, minute)."""
    hour, minute = parse_daily_time(daily_time)
    tz = ZoneInfo(timezone)
    reference = (now or datetime.now(UTC)).astimezone(tz)
    local_run = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_run = local_run.astimezone(UTC)
    return utc_run.hour, utc_run.minute


def next_scheduled_run_utc(
    daily_time: str, timezone: str, *, now: datetime | None = None
) -> datetime:
    hour, minute = parse_daily_time(daily_time)
    tz = ZoneInfo(timezone)
    current = (now or datetime.now(UTC)).astimezone(tz)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)
