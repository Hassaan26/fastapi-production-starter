"""Database-level guarantees: constraints that must hold even if application code is bypassed."""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.base import Base
from app.models import Task, User
from tests.conftest import downgrade_migrations, run_migrations


def _user(email: str) -> User:
    return User(email=email, hashed_password="not-a-real-hash")


async def test_email_uniqueness_is_enforced_by_database(db_session: AsyncSession) -> None:
    db_session.add(_user("unique@example.com"))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_user("unique@example.com"))


async def test_invalid_task_status_is_rejected_by_check_constraint(
    db_session: AsyncSession,
) -> None:
    owner = _user("check@example.com")
    db_session.add(owner)
    await db_session.flush()

    with pytest.raises(IntegrityError, match="ck_tasks_status"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO tasks (id, owner_id, title, status) "
                    "VALUES (:id, :owner_id, 'Raw insert', 'blocked')"
                ),
                {"id": uuid.uuid4(), "owner_id": owner.id},
            )


async def test_task_requires_existing_owner(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Task(owner_id=uuid.uuid4(), title="Orphan"))


async def test_deleting_user_cascades_to_tasks(db_session: AsyncSession) -> None:
    owner = _user("cascade@example.com")
    db_session.add(owner)
    await db_session.flush()
    db_session.add_all([Task(owner_id=owner.id, title=f"T{i}") for i in range(3)])
    await db_session.flush()

    # Delete via SQL so the database's ON DELETE CASCADE does the work, not the ORM.
    await db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner.id})

    remaining = await db_session.scalar(
        select(func.count()).select_from(Task).where(Task.owner_id == owner.id)
    )
    assert remaining == 0


async def test_updated_at_changes_on_update(db_session: AsyncSession) -> None:
    owner = _user("timestamps@example.com")
    db_session.add(owner)
    await db_session.flush()

    # now() is fixed for the whole transaction, so first move updated_at into the past.
    await db_session.execute(
        text("UPDATE users SET updated_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": owner.id},
    )
    await db_session.refresh(owner)
    stale = owner.updated_at

    owner.is_active = False
    await db_session.flush()

    assert owner.updated_at > stale


def _schema_diff(connection: Connection) -> list:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return compare_metadata(context, Base.metadata)


async def test_migrations_match_models(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        diff = await conn.run_sync(_schema_diff)
    assert diff == [], f"Models and migrations are out of sync: {diff}"


async def test_migrations_downgrade_and_upgrade_cleanly(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(downgrade_migrations)
        tables = await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name IN ('users', 'tasks')"
            )
        )
        assert tables == 0
        await conn.run_sync(run_migrations)
