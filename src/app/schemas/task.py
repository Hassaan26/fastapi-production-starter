import uuid
from datetime import UTC, datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models.task import TaskStatus

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, Field(max_length=5000)]
# Require an explicit offset, then normalize to UTC so every response uses the same zone
# (otherwise a create would echo the client's offset while later reads return UTC).
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]


class TaskCreate(BaseModel):
    # extra="forbid" blocks mass assignment: a client cannot smuggle in `owner_id`.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "title": "Write the README",
                    "description": "Cover setup, architecture and limitations.",
                    "status": "todo",
                    "due_at": "2026-11-01T17:00:00Z",
                }
            ]
        },
    )

    title: Title
    description: Description | None = None
    status: TaskStatus = TaskStatus.TODO
    due_at: UtcDatetime | None = None


class TaskUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"status": "in_progress"}]}
    )

    title: Title | None = None
    description: Description | None = None
    status: TaskStatus | None = None
    due_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        # `description` and `due_at` may be cleared with null; required columns may not.
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"'{name}' cannot be null.")
        return self


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
