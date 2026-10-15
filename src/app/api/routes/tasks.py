import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.models import TaskStatus
from app.schemas.common import Page, error_responses
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services import tasks as task_service

router = APIRouter(prefix="/tasks", tags=["tasks"], responses=error_responses(401, 403, 422))


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, user: CurrentUser, session: SessionDep) -> TaskRead:
    task = await task_service.create_task(session, user.id, data)
    return TaskRead.model_validate(task)


@router.get("", response_model=Page[TaskRead])
async def list_tasks(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    # Offset pagination is simple and fine at this scale; the cap bounds deep-page scans.
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    status: TaskStatus | None = None,
) -> Page[TaskRead]:
    """List the caller's tasks, newest first."""
    tasks, total = await task_service.list_tasks(
        session, user.id, limit=limit, offset=offset, status=status
    )
    return Page[TaskRead](
        items=[TaskRead.model_validate(task) for task in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskRead, responses=error_responses(404))
async def get_task(task_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> TaskRead:
    task = await task_service.get_task(session, user.id, task_id)
    return TaskRead.model_validate(task)


@router.patch("/{task_id}", response_model=TaskRead, responses=error_responses(404))
async def update_task(
    task_id: uuid.UUID, data: TaskUpdate, user: CurrentUser, session: SessionDep
) -> TaskRead:
    task = await task_service.update_task(session, user.id, task_id, data)
    return TaskRead.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404))
async def delete_task(task_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await task_service.delete_task(session, user.id, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
