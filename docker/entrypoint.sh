#!/bin/sh
set -e

# Development: the bind mount shadows the client generated into the image and
# the schema changes between phases, so regenerate on every start. Production
# images carry the generated client already; regenerating there only adds
# startup latency and a window where a healthcheck can see a half-written package.
if [ "${ENVIRONMENT:-development}" != "production" ]; then
  uv run prisma generate --schema /backend/prisma/schema.prisma
fi

exec "$@"
