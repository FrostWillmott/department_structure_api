from httpx import AsyncClient


async def test_create_department(client: AsyncClient) -> None:
    resp = await client.post("/departments/", json={"name": "Engineering"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Engineering"
    assert data["parent_id"] is None
    assert "id" in data
    assert "created_at" in data


async def test_create_department_trims_whitespace(client: AsyncClient) -> None:
    resp = await client.post("/departments/", json={"name": "  Engineering  "})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Engineering"


async def test_create_department_duplicate_name_same_parent(
    client: AsyncClient,
) -> None:
    await client.post("/departments/", json={"name": "Engineering"})
    resp = await client.post("/departments/", json={"name": "Engineering"})
    assert resp.status_code == 409


async def test_create_department_duplicate_name_different_parent(
    client: AsyncClient,
) -> None:
    parent1 = (await client.post("/departments/", json={"name": "Division A"})).json()
    parent2 = (await client.post("/departments/", json={"name": "Division B"})).json()
    await client.post(
        "/departments/", json={"name": "Backend", "parent_id": parent1["id"]}
    )
    resp = await client.post(
        "/departments/", json={"name": "Backend", "parent_id": parent2["id"]}
    )
    assert resp.status_code == 201


async def test_create_department_nonexistent_parent(client: AsyncClient) -> None:
    resp = await client.post(
        "/departments/", json={"name": "Backend", "parent_id": 9999}
    )
    assert resp.status_code == 404


async def test_create_employee(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.post(
        f"/departments/{dept['id']}/employees/",
        json={"full_name": "Ivan Ivanov", "position": "Developer"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["full_name"] == "Ivan Ivanov"
    assert data["position"] == "Developer"
    assert data["department_id"] == dept["id"]
    assert data["hired_at"] is None


async def test_create_employee_nonexistent_department(client: AsyncClient) -> None:
    resp = await client.post(
        "/departments/9999/employees/",
        json={"full_name": "Ivan Ivanov", "position": "Developer"},
    )
    assert resp.status_code == 404


async def test_get_department_tree(client: AsyncClient) -> None:
    parent = (await client.post("/departments/", json={"name": "Engineering"})).json()
    child = (
        await client.post(
            "/departments/", json={"name": "Backend", "parent_id": parent["id"]}
        )
    ).json()
    await client.post(
        f"/departments/{parent['id']}/employees/",
        json={"full_name": "Anna", "position": "Manager"},
    )

    resp = await client.get(f"/departments/{parent['id']}?depth=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["department"]["id"] == parent["id"]
    assert data["department"]["name"] == "Engineering"
    assert len(data["children"]) == 1
    assert data["children"][0]["id"] == child["id"]
    assert len(data["employees"]) == 1


async def test_get_department_excludes_employees(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    await client.post(
        f"/departments/{dept['id']}/employees/",
        json={"full_name": "Anna", "position": "Manager"},
    )

    resp = await client.get(f"/departments/{dept['id']}?include_employees=false")
    assert resp.status_code == 200
    assert resp.json()["employees"] == []


async def test_get_department_not_found(client: AsyncClient) -> None:
    resp = await client.get("/departments/9999")
    assert resp.status_code == 404


async def test_patch_rename_department(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.patch(f"/departments/{dept['id']}", json={"name": "R&D"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "R&D"


async def test_patch_move_to_root(client: AsyncClient) -> None:
    parent = (await client.post("/departments/", json={"name": "Engineering"})).json()
    child = (
        await client.post(
            "/departments/", json={"name": "Backend", "parent_id": parent["id"]}
        )
    ).json()

    resp = await client.patch(f"/departments/{child['id']}", json={"parent_id": None})
    assert resp.status_code == 200
    assert resp.json()["parent_id"] is None


async def test_patch_self_parent_reference(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.patch(
        f"/departments/{dept['id']}", json={"parent_id": dept["id"]}
    )
    assert resp.status_code == 400


async def test_patch_cycle_detection(client: AsyncClient) -> None:
    parent = (await client.post("/departments/", json={"name": "Engineering"})).json()
    child = (
        await client.post(
            "/departments/", json={"name": "Backend", "parent_id": parent["id"]}
        )
    ).json()

    resp = await client.patch(
        f"/departments/{parent['id']}", json={"parent_id": child["id"]}
    )
    assert resp.status_code == 409


async def test_delete_cascade(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    child = (
        await client.post(
            "/departments/", json={"name": "Backend", "parent_id": dept["id"]}
        )
    ).json()
    await client.post(
        f"/departments/{dept['id']}/employees/",
        json={"full_name": "Ivan", "position": "Dev"},
    )

    resp = await client.delete(f"/departments/{dept['id']}?mode=cascade")
    assert resp.status_code == 204

    assert (await client.get(f"/departments/{dept['id']}")).status_code == 404
    assert (await client.get(f"/departments/{child['id']}")).status_code == 404


async def test_delete_reassign(client: AsyncClient) -> None:
    source = (await client.post("/departments/", json={"name": "Old Team"})).json()
    target = (await client.post("/departments/", json={"name": "New Team"})).json()
    emp = (
        await client.post(
            f"/departments/{source['id']}/employees/",
            json={"full_name": "Ivan", "position": "Dev"},
        )
    ).json()

    resp = await client.delete(
        f"/departments/{source['id']}?mode=reassign"
        f"&reassign_to_department_id={target['id']}"
    )
    assert resp.status_code == 204

    target_data = (await client.get(f"/departments/{target['id']}")).json()
    assert any(e["id"] == emp["id"] for e in target_data["employees"])


async def test_delete_reassign_missing_target(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.delete(f"/departments/{dept['id']}?mode=reassign")
    assert resp.status_code == 400


async def test_patch_department_not_found(client: AsyncClient) -> None:
    resp = await client.patch("/departments/9999", json={"name": "Foo"})
    assert resp.status_code == 404


async def test_patch_nonexistent_new_parent(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.patch(f"/departments/{dept['id']}", json={"parent_id": 9999})
    assert resp.status_code == 404


async def test_patch_duplicate_name(client: AsyncClient) -> None:
    await client.post("/departments/", json={"name": "Engineering"})
    dept2 = (await client.post("/departments/", json={"name": "HR"})).json()
    resp = await client.patch(
        f"/departments/{dept2['id']}", json={"name": "Engineering"}
    )
    assert resp.status_code == 409


async def test_patch_move_to_parent_with_same_name(client: AsyncClient) -> None:
    parent_a = (await client.post("/departments/", json={"name": "Division A"})).json()
    parent_b = (await client.post("/departments/", json={"name": "Division B"})).json()
    dept_a = (
        await client.post(
            "/departments/", json={"name": "Backend", "parent_id": parent_a["id"]}
        )
    ).json()
    await client.post(
        "/departments/", json={"name": "Backend", "parent_id": parent_b["id"]}
    )

    resp = await client.patch(
        f"/departments/{dept_a['id']}", json={"parent_id": parent_b["id"]}
    )
    assert resp.status_code == 409


async def test_delete_not_found(client: AsyncClient) -> None:
    resp = await client.delete("/departments/9999?mode=cascade")
    assert resp.status_code == 404


async def test_delete_reassign_nonexistent_target(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.delete(
        f"/departments/{dept['id']}?mode=reassign&reassign_to_department_id=9999"
    )
    assert resp.status_code == 404


async def test_get_department_deep_tree(client: AsyncClient) -> None:
    root = (await client.post("/departments/", json={"name": "Root"})).json()
    level1 = (
        await client.post(
            "/departments/", json={"name": "Level1", "parent_id": root["id"]}
        )
    ).json()
    level2 = (
        await client.post(
            "/departments/", json={"name": "Level2", "parent_id": level1["id"]}
        )
    ).json()

    resp = await client.get(f"/departments/{root['id']}?depth=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["children"][0]["id"] == level1["id"]
    assert data["children"][0]["children"][0]["id"] == level2["id"]


async def test_get_employees_sorted_by_name(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    await client.post(
        f"/departments/{dept['id']}/employees/",
        json={"full_name": "Zara Jones", "position": "Dev"},
    )
    await client.post(
        f"/departments/{dept['id']}/employees/",
        json={"full_name": "Anna Smith", "position": "Lead"},
    )

    resp = await client.get(f"/departments/{dept['id']}?sort_employees_by=full_name")
    assert resp.status_code == 200
    names = [e["full_name"] for e in resp.json()["employees"]]
    assert names == ["Anna Smith", "Zara Jones"]


async def test_delete_reassign_to_self(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.delete(
        f"/departments/{dept['id']}?mode=reassign"
        f"&reassign_to_department_id={dept['id']}"
    )
    assert resp.status_code == 400


async def test_delete_reassign_to_descendant(client: AsyncClient) -> None:
    parent = (await client.post("/departments/", json={"name": "Parent"})).json()
    child = (
        await client.post(
            "/departments/", json={"name": "Child", "parent_id": parent["id"]}
        )
    ).json()
    resp = await client.delete(
        f"/departments/{parent['id']}?mode=reassign"
        f"&reassign_to_department_id={child['id']}"
    )
    assert resp.status_code == 400


async def test_patch_name_null_returns_422(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.patch(f"/departments/{dept['id']}", json={"name": None})
    assert resp.status_code == 422


async def test_create_employee_with_hired_at(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    resp = await client.post(
        f"/departments/{dept['id']}/employees/",
        json={
            "full_name": "Ivan Ivanov",
            "position": "Developer",
            "hired_at": "2023-01-15",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["hired_at"] == "2023-01-15"


async def test_get_department_depth_out_of_range(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    assert (await client.get(f"/departments/{dept['id']}?depth=0")).status_code == 422
    assert (await client.get(f"/departments/{dept['id']}?depth=6")).status_code == 422


async def test_create_department_rejects_whitespace_only_name(
    client: AsyncClient,
) -> None:
    resp = await client.post("/departments/", json={"name": "   "})
    assert resp.status_code == 422


async def test_delete_cascade_removes_nested_employees(client: AsyncClient) -> None:
    root = (await client.post("/departments/", json={"name": "Root"})).json()
    child = (
        await client.post(
            "/departments/", json={"name": "Child", "parent_id": root["id"]}
        )
    ).json()
    grandchild = (
        await client.post(
            "/departments/", json={"name": "Grandchild", "parent_id": child["id"]}
        )
    ).json()
    await client.post(
        f"/departments/{grandchild['id']}/employees/",
        json={"full_name": "Ivan", "position": "Dev"},
    )

    resp = await client.delete(f"/departments/{root['id']}?mode=cascade")
    assert resp.status_code == 204

    assert (await client.get(f"/departments/{child['id']}")).status_code == 404
    assert (await client.get(f"/departments/{grandchild['id']}")).status_code == 404


async def test_get_employees_default_sort_by_created_at(client: AsyncClient) -> None:
    dept = (await client.post("/departments/", json={"name": "Engineering"})).json()
    for name in ("Charlie", "Bob", "Alice"):
        await client.post(
            f"/departments/{dept['id']}/employees/",
            json={"full_name": name, "position": "Dev"},
        )
    resp = await client.get(f"/departments/{dept['id']}")
    names = [e["full_name"] for e in resp.json()["employees"]]
    assert names == ["Charlie", "Bob", "Alice"]
