"""Process-wide Prisma client. One engine per process (api, worker), handed to
repositories through dependency injection.

Startup connects with a bounded retry so a Postgres restart or a slow engine
boot does not kill the process; compose's `service_healthy` gate only covers
the cold-start case."""

import asyncio
from datetime import timedelta

from app.core.logging import get_logger
from app.db.generated import Prisma

logger = get_logger(__name__)

prisma_client = Prisma()

CONNECT_ATTEMPTS = 10
CONNECT_BASE_DELAY_SECONDS = 1.0
CONNECT_MAX_DELAY_SECONDS = 10.0
CONNECT_TIMEOUT = timedelta(seconds=10)


async def connect_db(
    *,
    attempts: int = CONNECT_ATTEMPTS,
    base_delay: float = CONNECT_BASE_DELAY_SECONDS,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await prisma_client.connect(timeout=CONNECT_TIMEOUT)
            return
        except Exception as exc:  # retried, then re-raised on the last attempt
            if attempt == attempts:
                logger.error("db_connect_failed", attempts=attempts, error=str(exc))
                raise
            delay = min(base_delay * 2 ** (attempt - 1), CONNECT_MAX_DELAY_SECONDS)
            logger.warning("db_connect_retry", attempt=attempt, delay_seconds=delay, error=str(exc))
            await asyncio.sleep(delay)


async def disconnect_db() -> None:
    if prisma_client.is_connected():
        await prisma_client.disconnect()
