from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


async def test_every_response_gets_a_generated_request_id(client: AsyncClient) -> None:
    first = await client.get("/health/live")
    second = await client.get("/health/live")

    assert len(first.headers["X-Request-ID"]) == 32
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


async def test_valid_incoming_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "trace-abc.123"})
    assert response.headers["X-Request-ID"] == "trace-abc.123"


async def test_unsafe_incoming_request_id_is_replaced(client: AsyncClient) -> None:
    # Prevents log injection / unbounded values from clients.
    response = await client.get("/health/live", headers={"X-Request-ID": "bad id\twith junk" * 10})
    assert response.headers["X-Request-ID"] != "bad id\twith junk" * 10
    assert len(response.headers["X-Request-ID"]) == 32


async def test_error_body_includes_matching_request_id(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist", headers={"X-Request-ID": "corr-42"})

    assert response.status_code == 404
    assert response.json()["error"]["request_id"] == "corr-42"
    assert response.json()["error"]["code"] == "not_found"


async def test_method_not_allowed_uses_error_format(client: AsyncClient) -> None:
    response = await client.put("/health/live")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_malformed_json_body_is_validation_error(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        content=b'{"email": "a@example.com", "password": ',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unhandled_exception_returns_generic_500(app: FastAPI) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    # raise_app_exceptions=False: Starlette re-raises after sending the 500; we want the response.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom", headers={"X-Request-ID": "boom-1"})

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "details": None,
        "request_id": "boom-1",
    }
    assert response.headers["X-Request-ID"] == "boom-1"
    assert "hunter2" not in response.text
