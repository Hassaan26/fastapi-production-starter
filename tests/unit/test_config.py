import pytest
from pydantic import ValidationError

from app.core.config import Settings

VALID = {
    "database_url": "postgresql+asyncpg://user:pass@localhost:5432/app",
    "jwt_secret_key": "x" * 32,
}


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**VALID, **overrides})  # type: ignore[arg-type]


def test_valid_settings_load() -> None:
    settings = make_settings()
    assert settings.access_token_expire_minutes == 30
    assert settings.rate_limit_enabled is True


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        make_settings(jwt_secret_key="too-short")


def test_sync_database_driver_is_rejected() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        make_settings(database_url="postgresql://user:pass@localhost/app")


def test_secret_is_masked_in_repr() -> None:
    assert "x" * 32 not in repr(make_settings())
