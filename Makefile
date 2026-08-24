# Dev workflow entry points. The Prisma CLI runs inside the api container so it
# always reads the same DATABASE_URL the app uses.
.PHONY: up down down-v logs ps test test-local lint seed prisma-generate prisma-migrate

up:
	docker compose up --build -d

down:
	docker compose down

down-v:
	docker compose down -v

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
