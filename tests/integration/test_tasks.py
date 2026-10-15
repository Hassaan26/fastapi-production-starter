from httpx import AsyncClient

from tests.conftest import AuthHeaders

TASKS = "/api/v1/tasks"


async def create_task(client: AsyncClient, headers: AuthHeaders, **fields) -> dict:
    response = await client.post(TASKS, json={"title": "A task", **fields}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- create -------------------------------------------------------------------------------


async def test_create_task_applies_defaults(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    response = await client.post(
        TASKS, json={"title": "  Write the README  "}, headers=auth_headers
    )

    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Write the README"
    assert task["status"] == "todo"
    assert task["description"] is None
    assert task["due_at"] is None
    assert task["created_at"] and task["updated_at"]
    assert "owner_id" not in task


async def test_create_task_with_all_fields(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    task = await create_task(
        client,
        auth_headers,
        title="Ship v1",
        description="Tag and release",
        status="in_progress",
        due_at="2026-11-01T17:00:00+05:00",
    )

    assert task["status"] == "in_progress"
    assert task["description"] == "Tag and release"
    assert task["due_at"] == "2026-11-01T12:00:00Z"  # stored and returned in UTC


async def test_create_task_validation_errors(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    response = await client.post(
        TASKS,
        json={"title": "", "status": "blocked", "description": "x" * 5001},
        headers=auth_headers,
    )

    assert response.status_code == 422
    locations = {tuple(d["loc"]) for d in response.json()["error"]["details"]}
    assert locations == {("body", "title"), ("body", "status"), ("body", "description")}


async def test_create_task_cannot_set_owner(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    response = await client.post(
        TASKS,
        json={"title": "Mass assignment", "owner_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["type"] == "extra_forbidden"


# --- read / list --------------------------------------------------------------------------


async def test_get_task(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    created = await create_task(client, auth_headers, title="Find me")

    response = await client.get(f"{TASKS}/{created['id']}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == created


async def test_get_unknown_task_is_not_found(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    response = await client.get(
        f"{TASKS}/0199e3c0-0000-7000-8000-000000000000", headers=auth_headers
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Task not found.",
        "details": None,
        "request_id": response.headers["X-Request-ID"],
    }


async def test_invalid_task_id_is_validation_error(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    response = await client.get(f"{TASKS}/not-a-uuid", headers=auth_headers)
    assert response.status_code == 422


async def test_list_tasks_paginates_newest_first(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    created = [await create_task(client, auth_headers, title=f"Task {i}") for i in range(5)]
    newest_first = [task["id"] for task in reversed(created)]

    pages = []
    for offset in (0, 2, 4):
        response = await client.get(
            TASKS, params={"limit": 2, "offset": offset}, headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert (body["limit"], body["offset"]) == (2, offset)
        pages.append([task["id"] for task in body["items"]])

    assert [len(page) for page in pages] == [2, 2, 1]
    assert [task_id for page in pages for task_id in page] == newest_first


async def test_list_tasks_filters_by_status(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    await create_task(client, auth_headers, title="Open")
    done = await create_task(client, auth_headers, title="Finished", status="done")

    response = await client.get(TASKS, params={"status": "done"}, headers=auth_headers)

    body = response.json()
    assert body["total"] == 1
    assert [task["id"] for task in body["items"]] == [done["id"]]


async def test_list_tasks_empty(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    response = await client.get(TASKS, headers=auth_headers)
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_tasks_rejects_out_of_range_pagination(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 10_001}):
        response = await client.get(TASKS, params=params, headers=auth_headers)
        assert response.status_code == 422, params


# --- update -------------------------------------------------------------------------------


async def test_patch_updates_only_given_fields(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    created = await create_task(client, auth_headers, title="Original", description="Keep me")

    response = await client.patch(
        f"{TASKS}/{created['id']}", json={"status": "done"}, headers=auth_headers
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "done"
    assert updated["title"] == "Original"
    assert updated["description"] == "Keep me"


async def test_patch_can_clear_optional_field(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    created = await create_task(client, auth_headers, description="Temporary")

    response = await client.patch(
        f"{TASKS}/{created['id']}", json={"description": None}, headers=auth_headers
    )

    assert response.json()["description"] is None


async def test_patch_rejects_null_title_and_empty_body(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    created = await create_task(client, auth_headers)

    for body in ({"title": None}, {}):
        response = await client.patch(f"{TASKS}/{created['id']}", json=body, headers=auth_headers)
        assert response.status_code == 422, body


# --- delete -------------------------------------------------------------------------------


async def test_delete_task(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    created = await create_task(client, auth_headers)

    response = await client.delete(f"{TASKS}/{created['id']}", headers=auth_headers)
    assert response.status_code == 204
    assert response.content == b""

    again = await client.get(f"{TASKS}/{created['id']}", headers=auth_headers)
    assert again.status_code == 404
