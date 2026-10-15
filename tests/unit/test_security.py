from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


async def test_hash_password_does_not_store_plaintext_and_verifies() -> None:
    hashed = await hash_password("correct-horse-battery-staple")

    assert "correct-horse-battery-staple" not in hashed
    assert hashed.startswith("$argon2id$")
    assert await verify_password("correct-horse-battery-staple", hashed)
    assert not await verify_password("wrong-password-123", hashed)


async def test_same_password_hashes_differently_each_time() -> None:
    # A random salt per hash means equal passwords are not recognizable in the database.
    assert await hash_password("same-password-123") != await hash_password("same-password-123")


def test_access_token_round_trip(test_settings: Settings) -> None:
    token, expires_in = create_access_token("user-123", test_settings)

    assert decode_access_token(token, test_settings) == "user-123"
    assert expires_in == test_settings.access_token_expire_minutes * 60


def _encode(test_settings: Settings, **overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": "user-123",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not None}
    return jwt.encode(payload, test_settings.jwt_secret_key.get_secret_value(), "HS256")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"exp": datetime.now(UTC) - timedelta(seconds=1)}, id="expired"),
        pytest.param({"sub": None}, id="missing-subject"),
        pytest.param({"exp": None}, id="missing-expiry"),
        pytest.param({"type": "refresh"}, id="wrong-token-type"),
    ],
)
def test_decode_rejects_invalid_claims(test_settings: Settings, overrides: dict) -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token(_encode(test_settings, **overrides), test_settings)


def test_decode_rejects_token_signed_with_another_key(test_settings: Settings) -> None:
    forged = jwt.encode(
        {
            "sub": "user-123",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "an-attacker-controlled-secret-key-0123456789",
        "HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forged, test_settings)


def test_decode_rejects_unsigned_alg_none_token(test_settings: Settings) -> None:
    unsigned = jwt.encode(
        {
            "sub": "user-123",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(unsigned, test_settings)


def test_decode_rejects_garbage(test_settings: Settings) -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("not-a-jwt", test_settings)
