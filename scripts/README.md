# Scripts

Ops helpers, run from `hyrebolt_backend/` against the compose stack.

| Script | Make target | What it does |
|---|---|---|
| `backup.sh [dir]` | `make db-backup` | `pg_dump -Fc` + resume-file tarball + applied-migrations list into `backups/<UTC timestamp>/`; keeps the newest 14. |
| `restore.sh <backup-dir>` | `make db-restore FROM=…` | Stops `api`/`worker`, `pg_restore --clean`, restores the resume files, restarts. Prompts before touching anything. |

See `docs/database.md` → *Backup and restore* for the retention/RPO notes and
the restore drill.
