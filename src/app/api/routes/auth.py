from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import SessionDep, SettingsDep, limit_login_attempts
from app.core.errors import AuthenticationError, ForbiddenError
from app.core.security import create_access_token
from app.schemas.common import error_responses
from app.schemas.user import Token, UserCreate, UserRead
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409, 422),
)
async def register(data: UserCreate, session: SessionDep) -> UserRead:
    user = await user_service.create_user(session, data)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(limit_login_attempts)],
    responses=error_responses(401, 403, 422, 429),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    settings: SettingsDep,
) -> Token:
    """OAuth2 password flow: send `username` (the email) and `password` as form fields.
    This also makes the "Authorize" button in /docs work."""
    user = await user_service.authenticate(session, form.username, form.password)
    if user is None:
        # Same message for unknown email and wrong password: no account enumeration here.
        raise AuthenticationError("Incorrect email or password.")
    if not user.is_active:
        raise ForbiddenError("This account is disabled.")

    token, expires_in = create_access_token(str(user.id), settings)
    return Token(access_token=token, expires_in=expires_in)
