# Dev workflow entry points. The Prisma CLI runs inside the api container so it
# always reads the same DATABASE_URL the app uses.
.PHONY: up down down-v logs ps test test-local lint seed prisma-generate prisma-migrate db-backup db-restore \
	prod-up prod-down prod-ps prod-logs prod-migrate prod-backup prod-restore

# --- Production (compose.prod.yml + .env.production, Caddy in front) ---------
# The env file is passed explicitly so ${DOMAIN} & co. interpolate in the
# compose file and the containers read the same values.
PROD := docker compose --env-file .env.production -f compose.prod.yml
PROD_SCRIPT_ENV := ENV_FILE=.env.production COMPOSE_FILE=compose.prod.yml COMPOSE_PROJECT_NAME=hyrebolt-prod

prod-up:
	$(PROD) up --build -d

prod-down:
	$(PROD) down

prod-ps:
	$(PROD) ps

prod-logs:
	$(PROD) logs -f api worker caddy

# Applies committed migrations only (never `migrate dev` in production).
prod-migrate:
	$(PROD) run --rm --no-deps api uv run prisma migrate deploy --schema /backend/prisma/schema.prisma

prod-backup:
	$(PROD_SCRIPT_ENV) sh scripts/backup.sh

# make prod-restore FROM=backups/<timestamp>
prod-restore:
	$(PROD_SCRIPT_ENV) sh scripts/restore.sh $(FROM)

up:
	docker compose up --build -d

down:
	docker compose down

# Destroys the database and resume volumes. Take a backup first.
down-v:
	@printf 'This deletes ALL data volumes. Run `make db-backup` first. Continue? [y/N] ' && read ans && [ "$$ans" = y ]
	docker compose down -v

db-backup:
	sh scripts/backup.sh

# make db-restore FROM=backups/<timestamp>
db-restore:
	sh scripts/restore.sh $(FROM)

logs:
	docker compose logs -f api

ps:
	docker compose ps

test:
	docker compose exec api uv run --group dev pytest

test-local:
	uv run pytest

lint:
	uv run ruff check app tests

seed:
	docker compose exec api uv run python -m app.db.seed

prisma-generate:
	docker compose exec api uv run prisma generate --schema /backend/prisma/schema.prisma

prisma-migrate:
	docker compose exec api uv run prisma migrate dev --schema /backend/prisma/schema.prisma
