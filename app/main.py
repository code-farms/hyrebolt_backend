from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, health, search, users
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.http import close_http_client
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis_client
from app.db.client import connect_db, disconnect_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await connect_db()
    logger.info("startup_complete")
    yield
    await close_http_client()
    await close_redis_client()
    await disconnect_db()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title="Job Agent API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(search.router)

    return app


app = create_app()
