"""Manual task trigger for ops/verification:

    python -m app.worker.enqueue daily_job_search
"""

import asyncio
import sys

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings

VALID_TASKS = {"daily_job_search", "analyze_new_jobs", "match_jobs", "send_daily_digest"}


async def main(task: str) -> None:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    job = await pool.enqueue_job(task)
    print(f"enqueued {task} as {job.job_id if job else '(duplicate job id, skipped)'}")
    await pool.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_TASKS:
        print(f"usage: python -m app.worker.enqueue <{'|'.join(sorted(VALID_TASKS))}>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
