from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api import api_router
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import build_engine, build_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(settings.database_url)
        app.state.sessionmaker = build_sessionmaker(engine)
        app.state.redis = (
            Redis.from_url(settings.redis_url) if settings.rate_limit_enabled else None
        )
        try:
            yield
        finally:
            if app.state.redis is not None:
                await app.state.redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="FastAPI Production Starter",
        version="0.1.0",
        description="A small task-management API demonstrating backend fundamentals.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.redis = None

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    return app
