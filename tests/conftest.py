import os
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Importing app.main builds the app, which instantiates Settings. Provide the
# required values up front so the suite runs on a fresh clone without a .env.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")

from app.api.deps import (
    get_profile_repository,
    get_redis,
    get_skill_repository,
    get_user_repository,
)
from app.main import app
from tests.fakes import (
    FakeDB,
    FakeProfileRepository,
    FakeRedis,
    FakeSkillRepository,
    FakeUserRepository,
)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client() -> AsyncIterator[tuple[AsyncClient, FakeDB, FakeRedis]]:
    """Client with all persistence swapped for in-memory fakes."""
    db = FakeDB()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_user_repository] = lambda: FakeUserRepository(db)
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(db)
    app.dependency_overrides[get_skill_repository] = lambda: FakeSkillRepository(db)
    app.dependency_overrides[get_redis] = lambda: fake_redis
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, db, fake_redis
    finally:
        app.dependency_overrides.clear()
