import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TaskStatus(enum.StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    # Every list query filters by owner and sorts by recency; this index serves both.
    __table_args__ = (Index("ix_tasks_owner_id_created_at", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # VARCHAR + CHECK instead of a native Postgres ENUM: adding a status later is a plain
    # constraint change rather than an ALTER TYPE migration.
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda members: [member.value for member in members],
        ),
        default=TaskStatus.TODO,
        server_default=TaskStatus.TODO.value,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
