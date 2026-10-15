from collections.abc import AsyncIterator

from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.db.session import get_session


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_when_dependencies_are_up(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_readiness_reports_redis_outage(client: AsyncClient, redis: FakeAsyncRedis) -> None:
    async def failing_ping() -> bool:
        raise RedisConnectionError("connection refused")

    redis.ping = failing_ping  # type: ignore[method-assign]

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "unavailable"}


async def test_readiness_reports_database_outage(app: FastAPI, client: AsyncClient) -> None:
    class UnreachableSession:
        async def execute(self, *args, **kwargs):
            raise OSError("connection refused")

    async def broken_session() -> AsyncIterator[UnreachableSession]:
        yield UnreachableSession()

    app.dependency_overrides[get_session] = broken_session

    response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["database"] == "unavailable"
    assert "connection refused" not in response.text  # no internal details leaked


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/api/v1/auth/login", "/api/v1/tasks", "/api/v1/tasks/{task_id}"} <= set(paths)
