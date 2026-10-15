"""Import every model here so `Base.metadata` is complete for Alembic and tests."""

from app.models.task import Task, TaskStatus
from app.models.user import User

__all__ = ["Task", "TaskStatus", "User"]
