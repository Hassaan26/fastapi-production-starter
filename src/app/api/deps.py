import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, ForbiddenError
from app.core.rate_limit import enforce_fixed_window
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> Redis | None:
    redis: Redis | None = request.app.state.redis
    return redis


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RedisDep = Annotated[Redis | None, Depends(get_redis)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep, settings: SettingsDep
) -> User:
    """Authentication: *who* is calling. Raises 401 if the token is missing or invalid,
    403 if the token is valid but the account has been deactivated."""
    subject = decode_access_token(token, settings)
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise AuthenticationError() from exc

    user = await session.get(User, user_id)
    if user is None:
        raise AuthenticationError()
    if not user.is_active:
        raise ForbiddenError("This account is disabled.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def limit_login_attempts(request: Request, settings: SettingsDep, redis: RedisDep) -> None:
    if not settings.rate_limit_enabled or redis is None:
        return
    # Behind a reverse proxy this is the proxy's address unless uvicorn is started with
    # --proxy-headers and --forwarded-allow-ips for the trusted proxy.
    client_ip = request.client.host if request.client else "unknown"
    await enforce_fixed_window(
        redis,
        f"ratelimit:login:{client_ip}",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )
