# Hirebolt — Backend

FastAPI backend for Hirebolt: a personal, AI-assisted job search agent
that discovers jobs from multiple sources, normalizes and deduplicates them,
matches them against your profile, ranks the results, and surfaces the best
ones in a dashboard.

> Renamed from "Job Agent" on 2026-08-30. Folder/package names keep the
> original `job_agent` identifiers; the display name is `APP_NAME` in
> `app/core/config.py`. The Docker Compose project is named `hirebolt`
> (containers `hirebolt-api-1`, `hirebolt-postgres-1`, …; volumes
> `hirebolt_*`). If you still have the old `job_agent_backend_*` volumes, copy
> them once before `make up`:
>
> ```sh
> for v in postgres_data resume_data; do
>   docker volume create hirebolt_$v
>   docker run --rm -v job_agent_backend_$v:/from:ro -v hirebolt_$v:/to alpine sh -c 'cp -a /from/. /to/'
> done
> ```

The project was built phase by phase (see `../phase-wise-plan.txt`); all 18
phases are implemented — auth, multi-source discovery, normalization and
deduplication, LLM-backed analysis and matching, ranking, resumes, application
tracking, notifications (in-app / email / Telegram), analytics and hardening.
See "Production deployment" below for running it behind Caddy.

The React frontend lives in its own repository: `job_agent_frontend` (a
sibling of this repo). This repo owns all infrastructure — Postgres, Redis,
and the API all run from the Docker Compose file here.

## Architecture

```
React (job_agent_frontend) ──HTTP──> FastAPI ──> Services ──> Repositories ──> PostgreSQL
                                        │
                                        └──> Redis  (broker for the background workers added in Phase 9)
```

Layering is enforced by directory, not convention alone: routers stay thin,
business logic lives in `services/`, and database access is confined to
repositories.

```
job_agent_backend/
├── app/
│   ├── main.py           App factory + lifespan (DB/Redis connect/disconnect)
│   ├── api/              Routers + dependency injection
│   ├── core/             Config, logging, exceptions, Redis
│   ├── db/               Prisma client singleton (+ gitignored generated client)
│   ├── models/           Domain models (later phases)
│   ├── repositories/     Database access layer (later phases)
│   ├── schemas/          Pydantic request/response schemas
│   ├── services/         Business logic
│   └── utils/
├── tests/                Pytest suite (httpx ASGI transport)
├── prisma/               Prisma schema + migrations (single source of truth)
├── workers/              Background workers (implemented in Phase 9)
├── docker/               API Dockerfile + entrypoint
├── docs/                 Reference docs added by later phases
├── scripts/              Dev/ops helper scripts
├── docker-compose.yml    postgres + redis + api
└── Makefile              up / down / logs / test / prisma-* targets
```

## Prerequisites

- Docker + Docker Compose
- [uv](https://docs.astral.sh/uv/) — only needed to run the backend or its
  tests outside Docker

## Environment variables

```bash
cp .env.example .env
```

| Variable | Purpose |
| --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres credentials |
| `POSTGRES_PORT` | Host-side Postgres port. Change on conflict. |
| `DATABASE_URL` | Connection string used **inside** containers (host `postgres`) |
| `DATABASE_URL_LOCAL` | Connection string for host-side DB clients |
| `REDIS_PORT` | Host-side Redis port. Change on conflict. |
| `REDIS_URL` | Redis URL used **inside** containers (host `redis`) |
| `ENVIRONMENT` | `development` / `test` / `production` |
| `LOG_LEVEL` / `LOG_FORMAT` | Structured logging config (`console` or `json`) |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API. Must include the frontend dev server origin (`http://localhost:5173`). |
| `BACKEND_PORT` | Host-side port for the API |

Secrets are never hardcoded — the app reads configuration from the environment
only, and `.env` is gitignored.

> **Port conflicts:** `POSTGRES_PORT` and `REDIS_PORT` are host-side bindings.
> If another project already uses 5432/6379, change these (e.g. `5433`/`6380`)
> and update `DATABASE_URL_LOCAL` to match. Container-internal URLs are
> unaffected.

## Running locally

```bash
cp .env.example .env
make up          # docker compose up --build -d
```

This starts three services: `postgres`, `redis`, and `api` (FastAPI with hot
reload). Each has a healthcheck; the API waits for Postgres and Redis to be
healthy before starting.

- API docs: http://localhost:8000/docs

```bash
make down        # stop, keep data
make down-v      # stop and drop the Postgres volume
make logs        # follow api logs
```

The frontend is started separately from the `job_agent_frontend` repo with
`pnpm dev` (see its README).

## Database setup

Prisma owns the schema and migrations. Because the backend is Python, the
Prisma CLI is run *inside the API container* (which has both Node and the
Python client generator), so it always reads the same `DATABASE_URL` the app
uses:

```bash
make prisma-migrate     # apply migrations / create one after editing prisma/schema.prisma
make prisma-generate    # regenerate the Python client only
make seed               # development-only seed (idempotent; no fake jobs)
```

FastAPI accesses Postgres exclusively through the generated `prisma-client-py`
client (`app/db/client.py`) — no SQLAlchemy. The generated client is
gitignored and regenerated on every container start, so a schema change never
leaves a stale client behind.

The full relational schema (users, profiles, skills, companies, sources, jobs,
matches, applications, search runs, notifications, watchlists) and its
conventions are documented in [docs/database.md](docs/database.md). The
pluggable job-source system (connectors, access methods, compliance rules) is
documented in [docs/job-sources.md](docs/job-sources.md).

## Testing

```bash
make test        # inside the container
make test-local  # on the host (uv run pytest)
make lint        # ruff over app/ and tests/
```

## Verifying the stack

```bash
make ps                                    # all three services healthy
curl http://localhost:8000/health/live     # {"status":"ok"}
curl http://localhost:8000/health          # postgres + redis both "ok"
```

`/health/live` is a dependency-free liveness probe (used by the container
healthcheck). `/health` is a readiness probe that checks Postgres and Redis and
returns 503 with a per-component breakdown when either is down.

## Production deployment (Caddy)

`compose.prod.yml` runs the whole product on one host behind Caddy, which
terminates TLS (Let's Encrypt, automatic) and serves the frontend and the API
from a single origin:

```
https://DOMAIN/            → Caddy → SPA bundle (built from ../job_agent_frontend)
https://DOMAIN/api/*       → Caddy → api:8000 (uvicorn --proxy-headers, non-root)
https://DOMAIN/health*     → Caddy → api:8000
                             worker (arq cron, 08:00 in TIMEZONE) · postgres · redis (appendonly)
```

Only Caddy publishes ports (80/443). Postgres, Redis and the API are reachable
solely on the compose network. The project is named `hirebolt-prod`, so it can
share a host with the dev stack.

### Prerequisites

- Docker Engine + Compose v2 on the server; ports 80 and 443 open.
- A DNS A/AAAA record for `DOMAIN` pointing at the server (needed for the
  certificate).
- Both repos checked out side by side: `job_agent_backend/` and
  `job_agent_frontend/` (the compose file builds the frontend image from
  `../job_agent_frontend`).

### First deploy

```bash
cp .env.production.example .env.production
# Fill in DOMAIN, ACME_EMAIL, POSTGRES_PASSWORD (+ DATABASE_URL), JWT_SECRET
# (`openssl rand -hex 32`), CORS_ORIGINS=https://DOMAIN, LLM_API_KEY,
# TELEGRAM_BOT_TOKEN. Placeholder secrets and non-https origins are refused.
make prod-up        # builds api/worker + frontend images, starts everything
make prod-migrate   # prisma migrate deploy (committed migrations only)
make prod-ps        # all five services healthy
```

Open `https://DOMAIN` — the landing page, then register the first account.
Save the Telegram chat ID under Settings › Notifications to receive the
daily digest.

### Updating

```bash
git -C ../job_agent_frontend pull && git pull
make prod-up        # rebuilds changed images, recreates only what changed
make prod-migrate   # no-op when the schema is unchanged
```

### Backups

```bash
make prod-backup                       # backups/<timestamp>/{db.dump,resume_data.tar.gz}
make prod-restore FROM=backups/<ts>    # destructive, asks for confirmation
```

Schedule `make prod-backup` from cron (e.g. daily at 03:00) and copy
`backups/` off the host. Compose volumes: `hirebolt-prod_postgres_data`,
`hirebolt-prod_resume_data`, `hirebolt-prod_redis_data`, `hirebolt-prod_caddy_data`.

### Operational notes

- Logs: `make prod-logs` (`LOG_FORMAT=json` for the API/worker).
- The daily agent runs at `DAILY_SEARCH_TIME` in `TIMEZONE` (`08:00
  Asia/Kolkata` = 02:30 UTC); the digest is sent right after. A change to
  either value needs a worker restart (`make prod-up`).
- An empty `LLM_API_KEY` silently selects the mock provider — check the
  `job_analyzed … model=` log line after the first run.
- Local smoke test: set `DOMAIN=localhost` (Caddy issues a self-signed
  certificate; use `curl -k`).
