#!/usr/bin/env sh
# Restore a backup taken by scripts/backup.sh. DESTRUCTIVE: replaces the
# current database contents and the resume files.
#
# Usage: scripts/restore.sh backups/<timestamp>
set -eu

SRC="${1:?usage: scripts/restore.sh <backup-dir>}"
[ -f "$SRC/db.dump" ] || { echo "no db.dump in $SRC" >&2; exit 1; }

ENV_FILE="${ENV_FILE:-.env}" # .env.production via `make prod-restore`
POSTGRES_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)"

echo "This will REPLACE database '$POSTGRES_DB' and all resume files with $SRC."
printf 'Type the database name to continue: '
read -r confirm
[ "$confirm" = "$POSTGRES_DB" ] || { echo "aborted"; exit 1; }

# Stop the app processes so nothing writes during the restore.
docker compose stop api worker

echo "→ restoring database"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists --no-owner --no-privileges < "$SRC/db.dump"

if [ -f "$SRC/resume_data.tar.gz" ]; then
  echo "→ restoring resume files"
  docker compose run --rm --no-deps -T --entrypoint sh api \
    -c 'rm -rf /backend/data/* && tar -xzf - -C /backend/data' < "$SRC/resume_data.tar.gz"
fi

docker compose start api worker
echo "✓ restore complete; pending migrations (if any) apply on next 'make prisma-migrate'"
