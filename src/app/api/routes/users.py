from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.common import error_responses
from app.schemas.user import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead, responses=error_responses(401, 403))
async def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
