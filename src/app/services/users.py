from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.security import dummy_password_hash, hash_password, verify_password
from app.models import User
from app.schemas.user import UserCreate


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    user = User(email=data.email, hashed_password=await hash_password(data.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        # Rely on the unique constraint rather than a pre-check: a SELECT-then-INSERT
        # would race with a concurrent registration for the same email.
        await session.rollback()
        raise ConflictError("A user with this email already exists.") from exc
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if the credentials are valid, otherwise None."""
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        await verify_password(password, dummy_password_hash())
        return None
    if not await verify_password(password, user.hashed_password):
        return None
    return user
