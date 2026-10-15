import pytest
from pydantic import ValidationError

from app.models import TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.user import UserCreate


def test_email_is_normalized_to_lowercase() -> None:
    user = UserCreate(email="Ada.Lovelace@Example.COM", password="correct-horse-battery")
    assert user.email == "ada.lovelace@example.com"


@pytest.mark.parametrize("password", ["short", "x" * 11, "x" * 129])
def test_password_length_policy(password: str) -> None:
    with pytest.raises(ValidationError):
        UserCreate(email="ada@example.com", password=password)


def test_task_title_is_stripped_and_must_not_be_blank() -> None:
    assert TaskCreate(title="  Buy milk  ").title == "Buy milk"
    with pytest.raises(ValidationError):
        TaskCreate(title="   ")


def test_task_create_defaults_to_todo() -> None:
    assert TaskCreate(title="Write tests").status is TaskStatus.TODO


def test_task_create_rejects_naive_datetimes() -> None:
    # Timezone-less timestamps are ambiguous; require an explicit offset.
    with pytest.raises(ValidationError):
        TaskCreate(title="Ship it", due_at="2026-11-01T17:00:00")  # type: ignore[arg-type]


def test_task_create_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title="Sneaky", owner_id="00000000-0000-0000-0000-000000000000")  # type: ignore[call-arg]


def test_task_update_tracks_only_provided_fields() -> None:
    update = TaskUpdate(status=TaskStatus.DONE)
    assert update.model_dump(exclude_unset=True) == {"status": TaskStatus.DONE}


def test_task_update_allows_clearing_optional_fields() -> None:
    update = TaskUpdate(description=None, due_at=None)
    assert update.model_dump(exclude_unset=True) == {"description": None, "due_at": None}


@pytest.mark.parametrize("payload", [{}, {"title": None}, {"status": None}])
def test_task_update_rejects_empty_or_null_required_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TaskUpdate(**payload)
