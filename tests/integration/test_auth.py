from datetime import UTC, datetime, timedelta

import jwt
from fakeredis import FakeAsyncRedis
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token
from app.models import User
from tests.conftest import TEST_PASSWORD, register

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/users/me"


async def login(client: AsyncClient, email: str, password: str = TEST_PASSWORD):
    return await client.post(LOGIN, data={"username": email, "password": password})


# --- registration -------------------------------------------------------------------------


async def test_register_creates_user_without_exposing_password(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER, json={"email": "Ada@Example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["is_active"] is True
    assert set(body) == {"id", "email", "is_active", "created_at"}
    assert TEST_PASSWORD not in response.text


async def test_register_stores_a_hash_not_the_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await register(client, "hash-check@example.com")

    user = await db_session.get(User, created["id"])
    assert user is not None
    assert user.hashed_password != TEST_PASSWORD
    assert user.hashed_password.startswith("$argon2id$")


async def test_register_duplicate_email_is_conflict_case_insensitive(client: AsyncClient) -> None:
    await register(client, "dup@example.com")

    response = await client.post(
        REGISTER, json={"email": "DUP@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_register_validation_error_does_not_echo_password(client: AsyncClient) -> None:
    response = await client.post(REGISTER, json={"email": "not-an-email", "password": "short-pw"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {tuple(detail["loc"]) for detail in error["details"]} == {
        ("body", "email"),
        ("body", "password"),
    }
    assert "short-pw" not in response.text


# --- login --------------------------------------------------------------------------------


async def test_login_returns_token_that_authenticates(client: AsyncClient) -> None:
    await register(client, "login@example.com")

    response = await login(client, "LOGIN@example.com")

    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == 30 * 60

    me = await client.get(ME, headers={"Authorization": f"Bearer {token['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"


async def test_login_wrong_password_and_unknown_email_look_identical(client: AsyncClient) -> None:
    await register(client, "victim@example.com")

    wrong_password = await login(client, "victim@example.com", "not-the-right-password")
    unknown_email = await login(client, "nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


async def test_login_disabled_account_is_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "disabled@example.com")
    await db_session.execute(
        update(User).where(User.email == "disabled@example.com").values(is_active=False)
    )

    response = await login(client, "disabled@example.com")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# --- authenticated requests ---------------------------------------------------------------


async def test_me_without_token_is_unauthorized(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_malformed_token_is_unauthorized(client: AsyncClient) -> None:
    response = await client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


async def test_me_with_expired_token_is_unauthorized(
    client: AsyncClient, test_settings: Settings
) -> None:
    user = await register(client, "expired@example.com")
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": user["id"], "type": "access", "iat": past, "exp": past + timedelta(minutes=30)},
        test_settings.jwt_secret_key.get_secret_value(),
        "HS256",
    )

    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_token_for_deleted_user_is_unauthorized(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    user, headers = await make_user()
    await db_session.delete(await db_session.get(User, user["id"]))
    await db_session.flush()

    response = await client.get(ME, headers=headers)

    assert response.status_code == 401


async def test_token_with_non_uuid_subject_is_unauthorized(
    client: AsyncClient, test_settings: Settings
) -> None:
    token, _ = create_access_token("not-a-uuid", test_settings)
    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_disabled_user_with_valid_token_is_forbidden(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    user, headers = await make_user()
    await db_session.execute(update(User).where(User.id == user["id"]).values(is_active=False))

    response = await client.get(ME, headers=headers)

    assert response.status_code == 403


# --- rate limiting ------------------------------------------------------------------------


async def test_login_is_rate_limited_per_client(
    client: AsyncClient, test_settings: Settings
) -> None:
    await register(client, "ratelimit@example.com")

    statuses = [
        (await login(client, "ratelimit@example.com", "wrong-password-123")).status_code
        for _ in range(test_settings.login_rate_limit)
    ]
    blocked = await login(client, "ratelimit@example.com")  # correct password, still blocked

    assert statuses == [401] * test_settings.login_rate_limit
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(blocked.headers["Retry-After"]) <= test_settings.login_rate_window_seconds


async def test_login_fails_open_when_redis_is_down(
    client: AsyncClient, redis: FakeAsyncRedis
) -> None:
    await register(client, "redis-down@example.com")
    redis.pipeline = lambda *a, **k: _BrokenPipeline()  # type: ignore[method-assign]

    response = await login(client, "redis-down@example.com")

    assert response.status_code == 200


class _BrokenPipeline:
    """Minimal stand-in for a Redis pipeline whose server is unreachable."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def incr(self, *args, **kwargs):
        return self

    expire = ttl = incr

    async def execute(self):
        raise RedisConnectionError("connection refused")
