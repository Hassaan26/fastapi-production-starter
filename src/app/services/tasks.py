"""Task business logic.

Authorization rule: a task is visible to, and modifiable by, its owner only. The rule is
enforced in every query's WHERE clause (not by fetching then checking), so there is no
code path that loads another user's task. A task owned by someone else is reported as
"not found" so the API does not reveal that it exists.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate


async def create_task(session: AsyncSession, owner_id: uuid.UUID, data: TaskCreate) -> Task:
    task = Task(owner_id=owner_id, **data.model_dump())
    session.add(task)
    await session.commit()
    return task


async def list_tasks(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
    status: TaskStatus | None = None,
) -> tuple[list[Task], int]:
    filters = [Task.owner_id == owner_id]
    if status is not None:
        filters.append(Task.status == status)

    total = await session.scalar(select(func.count()).select_from(Task).where(*filters))
    result = await session.scalars(
        select(Task)
        .where(*filters)
        # id breaks ties between rows created in the same transaction (same now()).
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result), total or 0


async def get_task(session: AsyncSession, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = await session.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
    if task is None:
        raise NotFoundError("Task not found.")
    return task


async def update_task(
    session: AsyncSession, owner_id: uuid.UUID, task_id: uuid.UUID, data: TaskUpdate
) -> Task:
    task = await get_task(session, owner_id, task_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    return task


async def delete_task(session: AsyncSession, owner_id: uuid.UUID, task_id: uuid.UUID) -> None:
    task = await get_task(session, owner_id, task_id)
    await session.delete(task)
    await session.commit()
