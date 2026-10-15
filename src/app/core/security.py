from datetime import UTC, datetime, timedelta
from functools import cache

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from starlette.concurrency import run_in_threadpool

from app.core.config import JWT_ALGORITHM, Settings
from app.core.errors import AuthenticationError

_password_hash = PasswordHash((Argon2Hasher(),))


# Argon2 is intentionally CPU- and memory-expensive. Running it in a worker thread keeps a
# login burst from blocking the event loop for every other request.
async def hash_password(password: str) -> str:
    return await run_in_threadpool(_password_hash.hash, password)


async def verify_password(password: str, hashed_password: str) -> bool:
    return await run_in_threadpool(_password_hash.verify, password, hashed_password)


@cache
def dummy_password_hash() -> str:
    """A real hash to verify against when the user does not exist, so that "unknown email"
    and "wrong password" take a similar amount of time (reduces user enumeration)."""
    return _password_hash.hash("dummy-password-for-constant-time-login")


def create_access_token(subject: str, settings: Settings) -> tuple[str, int]:
    """Return a signed JWT for `subject` and its lifetime in seconds."""
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "type": "access", "iat": now, "exp": now + lifetime}
    token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> str:
    """Validate signature, expiry and token type; return the subject (user ID)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],  # pinned: never let the token choose its algorithm
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError() from exc
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise AuthenticationError()
    subject: str = payload["sub"]
    return subject
