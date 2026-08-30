#!/usr/bin/env sh
# Dump the Postgres database (custom format, compressed) plus a tarball of the
# uploaded resume originals into ./backups/<timestamp>/. Both are taken from
# the running compose stack so nothing else needs to be installed.
#
# Usage: scripts/backup.sh [backup-root]   (default ./backups)
# Restore with scripts/restore.sh <backup-dir>.
set -eu

ROOT="${1:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$ROOT/$STAMP"
mkdir -p "$DEST"

# Load POSTGRES_* from the env file without exporting anything else.
# ENV_FILE=.env.production (with COMPOSE_FILE/COMPOSE_PROJECT_NAME) targets the
# production stack — see `make prod-backup`.
ENV_FILE="${ENV_FILE:-.env}"
POSTGRES_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)"

echo "→ pg_dump $POSTGRES_DB → $DEST/db.dump"
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DEST/db.dump"

echo "→ resume files → $DEST/resume_data.tar.gz"
docker compose exec -T api tar -czf - -C /backend/data . > "$DEST/resume_data.tar.gz"

# Keep the migration state next to the dump so a restore can be checked
# against the schema version it was taken from.
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  'SELECT migration_name FROM "_prisma_migrations" ORDER BY finished_at' > "$DEST/migrations.txt"

# Retention: keep the newest 14 backups.
ls -1dt "$ROOT"/*/ 2>/dev/null | tail -n +15 | xargs -r rm -rf

echo "✓ backup written to $DEST"
ls -la "$DEST"
