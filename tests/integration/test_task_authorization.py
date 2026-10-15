"""Cross-user access: one user must never read, list, modify or delete another user's tasks."""

import pytest
from httpx import AsyncClient

from tests.integration.test_tasks import TASKS, create_task

SOME_ID = "0199e3c0-0000-7000-8000-000000000000"


@pytest.fixture
async def alice_and_bob(make_user):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    return alice, bob


async def test_other_user_cannot_read_task(client: AsyncClient, alice_and_bob) -> None:
    alice, bob = alice_and_bob
    task = await create_task(client, alice, title="Alice's private task")

    response = await client.get(f"{TASKS}/{task['id']}", headers=bob)

    # 404 rather than 403 so Bob cannot even learn that the task exists.
    assert response.status_code == 404
    assert "Alice" not in response.text


async def test_other_user_cannot_update_task(client: AsyncClient, alice_and_bob) -> None:
    alice, bob = alice_and_bob
    task = await create_task(client, alice, title="Original")

    response = await client.patch(f"{TASKS}/{task['id']}", json={"title": "Hijacked"}, headers=bob)

    assert response.status_code == 404
    unchanged = await client.get(f"{TASKS}/{task['id']}", headers=alice)
    assert unchanged.json()["title"] == "Original"


async def test_other_user_cannot_delete_task(client: AsyncClient, alice_and_bob) -> None:
    alice, bob = alice_and_bob
    task = await create_task(client, alice)

    response = await client.delete(f"{TASKS}/{task['id']}", headers=bob)

    assert response.status_code == 404
    still_there = await client.get(f"{TASKS}/{task['id']}", headers=alice)
    assert still_there.status_code == 200


async def test_list_only_returns_own_tasks(client: AsyncClient, alice_and_bob) -> None:
    alice, bob = alice_and_bob
    await create_task(client, alice, title="Alice 1")
    await create_task(client, alice, title="Alice 2")
    bobs = await create_task(client, bob, title="Bob 1")

    response = await client.get(TASKS, headers=bob)

    body = response.json()
    assert body["total"] == 1
    assert [task["id"] for task in body["items"]] == [bobs["id"]]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", TASKS, None),
        ("POST", TASKS, {"title": "x"}),
        ("GET", f"{TASKS}/{SOME_ID}", None),
        ("PATCH", f"{TASKS}/{SOME_ID}", {"title": "x"}),
        ("DELETE", f"{TASKS}/{SOME_ID}", None),
    ],
)
async def test_task_endpoints_require_authentication(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    response = await client.request(method, path, json=body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
