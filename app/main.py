from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    agent,
    analytics,
    applications,
    assistant,
    auth,
    companies,
    dashboard,
    health,
    jobs,
    notifications,
    preferences,
    resumes,
    search,
    users,
)
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.http import close_http_client
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.redis import close_redis_client
from app.db.client import connect_db, disconnect_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await connect_db()
    logger.info("startup_complete")
    try:
        yield
    finally:
        # Each client is closed independently so one failing teardown never
        # leaks the others (the Prisma engine is a child process).
        for closer in (close_http_client, close_redis_client, disconnect_db):
            try:
                await closer()
            except Exception as exc:  # noqa: BLE001 - shutdown must run to completion
                logger.warning("shutdown_step_failed", step=closer.__name__, error=str(exc))
        logger.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    # Interactive docs are a development aid; the OpenAPI document enumerates
    # every route and schema, so none of it is served in production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Job Agent API",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Starlette wraps in call order, so the LAST add_middleware is the
    # outermost layer. Innermost → outermost: body cap (rejects before the
    # route reads anything), security headers (stamped on every response,
    # 413s and CORS preflights included), request id + access log around all.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestLoggingMiddleware)

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(search.router)
    app.include_router(jobs.router)
    app.include_router(agent.router)
    app.include_router(notifications.router)
    app.include_router(dashboard.router)
    app.include_router(applications.router)
    app.include_router(companies.router)
    app.include_router(resumes.router)
    app.include_router(assistant.router)
    app.include_router(preferences.router)
    app.include_router(analytics.router)

    return app


app = create_app()
