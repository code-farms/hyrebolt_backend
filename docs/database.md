# Database

PostgreSQL, with the schema owned by **Prisma** (`prisma/schema.prisma`) and
accessed from FastAPI exclusively through the generated **prisma-client-py**
asyncio client. There is no SQLAlchemy anywhere in the codebase, by design.

## Why Prisma with a Python backend

The schema, its migrations, and the generated client all derive from one file
(`prisma/schema.prisma`), so the database can never drift from what the code
expects. The trade-off is that the Prisma CLI is a Node tool: the api Docker
image ships Node for exactly this reason, and all schema commands run inside
the api container so they read the same `DATABASE_URL` the app uses.

## How FastAPI accesses PostgreSQL

- `prisma generate` writes an asyncio Python client to `app/db/generated/`
  (gitignored; regenerated at image build and on every container start by
  `docker/entrypoint.sh`).
- `app/db/client.py` holds the singleton `Prisma()` instance, connected and
  disconnected by the FastAPI lifespan in `app/main.py`.
- Route handlers never touch the client directly. Dependency injection
  (`app/api/deps.py`) hands repositories (`app/repositories/`) to services;
  all queries live in repositories.
- `app/models/` re-exports the generated schema enums as the app's stable
  domain vocabulary.

## Migration workflow

1. Edit `prisma/schema.prisma`.
2. `make prisma-migrate` — runs `prisma migrate dev` inside the api container:
   writes a new SQL file under `prisma/migrations/`, applies it, and
   regenerates the client.
3. Commit the schema **and** the new migration folder together.

`make prisma-generate` regenerates the client without touching migrations.
For host-side work (pytest, IDE types), run
`uv run prisma generate --schema prisma/schema.prisma` on the host too.

## Seed (development only)

```bash
make seed        # idempotent — safe to re-run
```

`app/db/seed.py` refuses to run when `ENVIRONMENT=production`. It seeds
reference data (canonical skills, the 11 job-source rows — all `enabled=false`
until their connectors exist) and one dev user (`dev@example.com`, password
`devpassword123` — development only) with a profile and skills. **It never
creates Job rows** — jobs only ever come from real discovery.

## Schema conventions

- **IDs**: `uuid()` strings everywhere; safe to expose publicly.
- **Timestamps**: `createdAt` / `updatedAt` on every table.
- **Soft delete** (`deletedAt`) only on `User`, `Job`, `Application` — the
  tables whose history feeds matching and analytics. Join tables delete hard:
  a tombstone there would collide with the row's `@@unique` key on re-create.
- **Job ↔ sources**: `Job` carries the primary listing's
  `externalId/sourceId/sourceUrl/canonicalUrl`; `JobSourceListing` stores
  *every* listing (`isPrimary` marks the one mirrored on Job). The
  `@@unique([sourceId, externalId])` constraint lives on the listing table
  only — on `Job` it would break the first cross-source merge. Postgres
  treats NULL `externalId`s as distinct, so ID-less listings never collide.
- **`canonicalUrl` / `contentHash` are indexed, not unique.** Deduplication
  (Phase 6) must never blind-merge on a single signal; uniqueness decisions
  belong to the dedup service's confidence threshold. `duplicateOfId` links
  near-duplicates below the auto-merge threshold without merging them.
- **Company resolution can fail**: `Job.companyName` (raw text) is required,
  `Job.companyId` is nullable and set-null on company deletion. `Company`
  startup metadata (stage, industry, …) is nullable — never fabricated, and
  connectors only ever fill columns that are still null (Phase 13);
  `metadataSource` records where a value came from (`company_careers`, `user`).
- **`JobMatch.watchlistScore`** (Phase 13) is null unless the job's company is
  on the user's watchlist; `scoringVersion` is set to `"stale"` for a user's
  matches at a company whenever their watchlist entry changes, so the nightly
  `match_jobs` re-scores them.
- **Search-friendly fields without preview features**: `normalizedTitle` and
  `normalizedLocation` are btree-indexed (including the composite pair used
  by dedup's company+title+location signal). Prisma's full-text search is a
  preview feature unsupported by prisma-client-py, so a `tsvector` + GIN
  index will be added later via raw SQL in a migration if discovery needs it.
- **Idempotency anchors for workers** (Phase 9): `JobMatch` is unique per
  `(userId, jobId)` and `Notification.dedupeKey` is unique, so retries can
  never double-score or double-send.
- **Delete behavior**: user-owned and job-owned children cascade; catalog
  references (`Skill`, `JobSource`) and `Job → Application` are `Restrict`
  (application history must never vanish because a job was purged);
  `Company → Job` and `Job.duplicateOf` are `SetNull`.

## Entity map

```
User ─1:1─ UserProfile ─1:N─ UserSkill ─N:1─ Skill
  │                                            │
  ├─1:N─ SavedJob ────N:1─┐                    │
  ├─1:N─ Application ─N:1─┤   ┌─1:N─ JobSkill ─┘
  ├─1:N─ JobMatch ────N:1─┼── Job ─N:1─ Company ─1:N─ CompanyWatchlist ─N:1─ User
  ├─1:N─ Notification     │    ├─N:1─ JobSource
  ├─1:N─ SearchRun        │    ├─1:N─ JobSourceListing ─N:1─ JobSource
  └─1:N─ CompanyWatchlist │    └─self─ duplicateOf/duplicates
                          │
      Application ─1:N─ ApplicationEvent
```
