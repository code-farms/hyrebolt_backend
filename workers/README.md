# Background workers

The daily agent runs on **arq** (async, Redis-backed). Code lives in
`app/worker/`; this directory documents operations.

## What runs

One `worker` container (see `docker-compose.yml`) hosts both the scheduler
and the task executor:

- **Cron**: `daily_job_search` fires once a day at `DAILY_SEARCH_TIME` in
  `TIMEZONE` (default 08:00 Asia/Kolkata; converted to UTC at worker startup).
- **Chain**: daily_job_search → analyze_new_jobs → match_jobs →
  send_daily_digest, linked by deterministic per-date arq job ids so a
  re-trigger can never fan out twice.

## Idempotency

- daily_job_search: Redis `SET NX` date key — one run per calendar day.
- analyze_new_jobs: one `JobAnalysis` row per job (unique) per prompt version.
- match_jobs: one `JobMatch` per (user, job) (unique) per scoring version.
- send_daily_digest: `Notification.dedupeKey = digest:{userId}:{date}`
  (unique) — a crashed retry can never double-notify.

## Retries / dead letter

Tasks retry up to `max_tries=3` (arq re-defers on exception). The terminal
failure is logged as `task_failed_permanently`; arq keeps the job result in
Redis as the dead-letter record.

## Operations

```bash
docker compose logs -f worker                 # watch the agent
docker compose exec worker uv run python -m app.worker.enqueue daily_job_search
docker compose exec worker uv run arq --check app.worker.settings.WorkerSettings
```

`GET /api/v1/agent/status` (authenticated) reports last/next run, matches and
notifications in the last 24h, failures, and worker health.
