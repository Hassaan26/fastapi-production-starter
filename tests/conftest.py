"""Test fixtures.

Integration tests run against a real PostgreSQL database (TEST_DATABASE_URL). The schema is
built once per session by running the Alembic migrations, so the migrations themselves are
exercised by every run. Each test then runs inside an outer transaction that is rolled back
afterwards; the app's own commits become SAVEPOINT releases. Tests are isolated without
truncating tables, and stay fast.
"""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_redis
from app.core.config import Settings
from app.core.security import create_access_token
from app.db.session import get_session
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]

# Environment variable wins (CI); otherwise read just this one key from a local .env.
# (Not load_dotenv: that would leak every local setting into the process for all tests.)
TEST_DATABASE_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or dotenv_values(ROOT / ".env").get("TEST_DATABASE_URL")
    or "postgresql+asyncpg://postgres:postgres@localhost:5432/app_test"
)
TEST_PASSWORD = "correct-horse-battery-staple"

AuthHeaders = dict[str, str]


def _assert_safe_test_database(url: str) -> None:
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run: test database {database!r} must end in '_test' "
            "because the suite drops and recreates its schema."
        )


async def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    admin_engine = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    await admin_engine.dispose()


def _alembic_config(connection: Connection) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def run_migrations(connection: Connection, revision: str = "head") -> None:
    command.upgrade(_alembic_config(connection), revision)


def downgrade_migrations(connection: Connection, revision: str = "base") -> None:
    command.downgrade(_alembic_config(connection), revision)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        database_url=TEST_DATABASE_URL,
        jwt_secret_key="test-only-secret-key-that-is-long-enough-0123456789",
        rate_limit_enabled=True,
        login_rate_limit=5,
        login_rate_window_seconds=60,
        log_level="WARNING",
        log_json=False,
    )


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    _assert_safe_test_database(TEST_DATABASE_URL)
    await _ensure_database_exists(TEST_DATABASE_URL)

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(run_migrations)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    await client.flushall()
    yield client
    await client.aclose()


@pytest.fixture
def app(test_settings: Settings, db_session: AsyncSession, redis: FakeAsyncRedis) -> FastAPI:
    app = create_app(test_settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_redis] = lambda: redis
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def register(client: AsyncClient, email: str, password: str = TEST_PASSWORD) -> dict:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def make_user(
    client: AsyncClient, test_settings: Settings
) -> Callable[..., Awaitable[tuple[dict, AuthHeaders]]]:
    """Register a user through the API and return (user_json, auth_headers).

    The token is minted directly rather than via /login so tests don't consume the login
    rate-limit budget; the login endpoint has its own dedicated tests.
    """

    async def _make_user(email: str | None = None) -> tuple[dict, AuthHeaders]:
        user = await register(client, email or f"user-{uuid.uuid4().hex[:8]}@example.com")
        token, _ = create_access_token(user["id"], test_settings)
        return user, {"Authorization": f"Bearer {token}"}

    return _make_user


@pytest.fixture
async def auth_headers(
    make_user: Callable[..., Awaitable[tuple[dict, AuthHeaders]]],
) -> AuthHeaders:
    _, headers = await make_user()
    return headers
