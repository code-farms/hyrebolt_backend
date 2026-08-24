#!/bin/sh
set -e

# Regenerated on every start because the dev bind mount shadows the copy built
# into the image, and because the schema changes between phases.
uv run prisma generate --schema /backend/prisma/schema.prisma

exec "$@"
