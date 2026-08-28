FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_NO_SYNC=1 \
    UV_CACHE_DIR=/home/app/.cache/uv \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/app

# nodejs/npm are needed by the Prisma CLI, which prisma-client-py shells out to
# for `generate` and `migrate`. curl backs the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /backend

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# prisma/schema.prisma generates the Python client into ../app/db/generated
# (a path relative to itself), so prisma/ and app/ must stay siblings — the
# image mirrors the repo layout under /backend.
COPY prisma prisma
COPY app app
COPY tests tests

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /backend/data \
    && chown -R app:app /backend /home/app

# Everything from here runs unprivileged, including the Prisma CLI/engine
# warm-up, so its cache lands in the runtime user's home.
USER app

# Warm the Prisma CLI + engine download into the image so container start is fast.
RUN uv run prisma generate --schema prisma/schema.prisma

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Production command: no reloader, trust proxy headers from FORWARDED_ALLOW_IPS
# (uvicorn reads that env var) so rate limits see the real client address.
# docker-compose.yml overrides this with a --reload command for development.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
