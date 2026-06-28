# DECISIONS

> Key architectural decisions: what was done, why, and what alternatives were considered.

---

## Contents

1. [Architecture: three layers](#1-architecture-three-layers)
2. [Department tree and nodes](#2-department-tree-and-nodes)
3. [Recursive CTE](#3-recursive-cte)
4. [BFS and cycle detection](#4-bfs-and-cycle-detection)
5. [PATCH and model_fields_set](#5-patch-and-model_fields_set)
6. [Deletion: cascade vs reassign](#6-deletion-cascade-vs-reassign)
7. [Cascade: DB + ORM (passive_deletes)](#7-cascade-db--orm-passive_deletes)
8. [Name uniqueness](#8-name-uniqueness)
9. [Async, sessions, get_db](#9-async-sessions-get_db)
10. [expire_on_commit](#10-expire_on_commit)
11. [Configuration and environments](#11-configuration-and-environments)
12. [SQLAlchemy 2.0: new syntax](#12-sqlalchemy-20-new-syntax)
13. [Tests](#13-tests)

---

## 1. Architecture: three layers

**Decision:** split into `routers/` (HTTP) → `services/` (business logic) → `database.py` (DB access).

**Why:**
- Routers handle only HTTP: parse the request, call the service, convert domain exceptions to `HTTPException`.
- Services contain all business logic (validation, cycles, cascades) and **have no knowledge of HTTP** — they can be tested and reused outside a web context.
- Domain exceptions (`app/exceptions.py`) are the contract between layers: the service raises `DepartmentNotFoundError`, the router decides that means 404.

**Alternatives:**
- A repository layer between the service and SQLAlchemy. **Deliberately omitted:** at this scale it would add abstraction with no practical benefit. Services call SQLAlchemy directly.
- All logic in routers — rejected: mixes HTTP concerns with business rules, hard to test.

---

## 2. Department tree and nodes

**Decision:** departments form a self-referential tree via `parent_id` (FK to the same table). Stored flat in the DB, returned as a nested tree in the API.

```
id | name        | parent_id        Company
1  | Company     | null         ->   ├── Engineering
2  | Engineering | 1                 │    ├── Backend
3  | Backend     | 2                 │    └── Frontend
4  | Frontend    | 2                 └── HR
5  | HR          | 1
```

- `parent_id = null` → root department.
- `parent_id = X` → child of department X.

**Nodes (`DepartmentTreeNode`):** Pydantic schema for the **nested** representation.

Three schemas and their purpose:

| Schema | Contents | Used for |
|---|---|---|
| `DepartmentBase` | id, name, parent_id, created_at | POST/PATCH responses (single department) |
| `DepartmentTreeNode` | `DepartmentBase` + `children: list[DepartmentTreeNode]` | nested children in GET response |
| `DepartmentTreeResponse` | `department` + `employees` + `children` | full GET response |

`DepartmentTreeNode` references itself in `children` → recursive schema → tree of arbitrary depth.

**Why the tree is assembled in code rather than stored nested:**
- A relational DB stores data flat; nesting is a presentation concern.
- The same department can be queried as the root of a subtree with different `depth` values, so the tree is built per request.

---

## 3. Recursive CTE

**Decision:** `GET /departments/{id}` uses a recursive CTE in PostgreSQL to fetch the subtree in a single query.

**Why:**
- The alternative is to query the DB recursively for each level (N+1 queries). A CTE does it in one query on the DB side.
- The alternative of `relationship("children")` with lazy loading is prone to N+1 and works poorly with async. Rejected.

**How it works:**

```sql
WITH RECURSIVE tree AS (
    -- anchor: starting point, level = 0
    SELECT id, name, parent_id, created_at, 0 AS level
    FROM departments WHERE id = :dept_id

    UNION ALL

    -- recursive part: children of rows already in tree
    SELECT d.id, d.name, d.parent_id, d.created_at, tree.level + 1
    FROM departments d
    JOIN tree ON d.parent_id = tree.id
    WHERE tree.level < :depth
)
SELECT * FROM tree ORDER BY name;
```

Step by step (PostgreSQL drives the loop):
1. Executes the anchor → root row in `tree`.
2. Executes the recursive part against the current `tree` → finds children.
3. Repeats step 2 until the recursive part returns no new rows or `level < depth` is false.
4. Stops when no new rows are produced.

**Important details:**
- `level` is a computed column (`literal(0).label("level")` in the anchor, `base.c.level + 1` in the recursion). It does not exist in the table — it is calculated because depth is relative to whichever root we start from.
- `depth` (validated 1–5 in the router) limits traversal: `WHERE level < depth`.
- `.c` (`base.c.id`, `base.c.level`) — access to CTE columns. This is SQLAlchemy API (`c` = columns), not FastAPI.
- In Python there is **one** `await db.execute(...)`; the loop runs inside PostgreSQL.
- Lines 95–117 of the service only **build** the SQL; the query is sent to the DB at `db.execute` (line 118).

**After the CTE** — tree assembly in Python:

```python
dept_map = { row.id: DepartmentTreeNode(...) for row in rows }  # nodes with empty children
for row in rows:
    if row.parent_id in dept_map and row.id != dept_id:
        dept_map[row.parent_id].children.append(dept_map[row.id])
```

**Employees** — fetched in a separate query, only for the requested department (not the whole subtree). Sorted by `created_at` or `full_name`. When `include_employees=false` the query is skipped.

---

## 4. BFS and cycle detection

**Decision:** before changing `parent_id`, collect all descendants of the department via BFS and verify that the new parent is not among them.

**Why BFS instead of a CTE here:**
- Only a set of descendant IDs is needed (`set[int]`), not full row data.
- The check logic lives in Python alongside the rest of the PATCH/DELETE business logic.

**Code (`_get_descendants_ids`):**

```python
result: set[int] = set()
queue = [dept_id]
while queue:
    rows = await db.execute(
        select(Department.id).where(Department.parent_id.in_(queue))
    )
    queue = []
    for (child_id,) in rows:
        if child_id not in result:
            result.add(child_id)
            queue.append(child_id)
return result
```

- `queue` starts with `dept_id` — the search origin (its children); `dept_id` itself is not added to `result`.
- One SQL query per tree level (`parent_id IN (...)`).
- `while queue` — the BFS idiom: "while there are unprocessed nodes". Stops when no children are found (`queue` is empty).
- `if child_id not in result` — guards against infinite loops on corrupt data.

**Usage:**
- PATCH: `if new_parent_id in descendants → CycleDetectedError (409)`.
- DELETE reassign: `if reassign_to_id in descendants → InvalidReassignTargetError (400)`.

**Why BFS instead of Python recursion:** no recursion limit, one query per level, easier to read.

---

## 5. PATCH and model_fields_set

**Problem:** in PATCH we need to distinguish three cases:
- field **not provided** → do not change;
- field provided as **null** → meaningful action (for `parent_id` — move to root);
- field provided with a **value** → set it.

A plain `if data.parent_id is None` check cannot tell "not provided" from "explicitly sent null".

**Solution:** `model_fields_set` — the set of fields actually present in the request.

```python
if "parent_id" in data.model_fields_set:
    new_parent_id = data.parent_id   # may be None (= move to root)
```

| Request body | `"parent_id" in model_fields_set` | Action |
|---|---|---|
| `{"name": "X"}` | False | parent unchanged |
| `{"parent_id": null}` | True, value None | move to root |
| `{"parent_id": 5}` | True, value 5 | move under 5 |

**Protecting name from null:** `name: null` is rejected by a `model_validator` — the name cannot be cleared, the field is simply omitted. For `parent_id` null is valid (it means "move to root").

**Check order in `update_department`:**
1. Does the department exist? Otherwise 404.
2. If `parent_id` is changing:
   - not self-referential → `SelfParentReferenceError` (400);
   - new parent exists? otherwise 404;
   - new parent is not a descendant (BFS) → `CycleDetectedError` (409);
   - if name is not changing — check name uniqueness under the new parent.
3. If `name` is changing — check uniqueness under the effective parent.
4. commit; on `IntegrityError` — rollback and `DuplicateDepartmentNameError`.

---

## 6. Deletion: cascade vs reassign

**Decision:** two modes via the `mode` query parameter.

### cascade

```python
await db.delete(dept)   # DB cascades deletion to children and employees
await db.commit()
```

Deletes the department, the entire subtree, and all their employees (via `ON DELETE CASCADE`).

### reassign

```python
await db.execute(
    update(Employee)
    .where(Employee.department_id == dept_id)
    .values(department_id=reassign_to_id)
)
await db.delete(dept)
await db.commit()
```

Moves **only the direct** employees of the deleted department to the target, then deletes the department. Child departments and their employees are still deleted by cascade.

| | cascade | reassign |
|---|---|---|
| employees of the deleted department | deleted | moved to target |
| child departments | deleted | deleted |
| employees of child departments | deleted | deleted |

**Important:** reassign does not "save the whole subtree" — it only preserves the people from the deleted department itself. This is an intentional contract: child branches are considered part of the deleted structure.

**Guards for reassign:**
- no `reassign_to_id` → `InvalidDeleteModeError` (400);
- target == the department itself → `InvalidReassignTargetError` (400);
- target does not exist → `ReassignTargetNotFoundError` (404);
- target is a descendant of the deleted department (BFS) → `InvalidReassignTargetError` (400). Otherwise employees would be moved to a department that is immediately deleted by cascade.

---

## 7. Cascade: DB + ORM (passive_deletes)

Cascaded deletion operates at **two levels**, and this is intentional:

1. **DB:** FKs are declared with `ON DELETE CASCADE` (both `parent_id` and `Employee.department_id`). PostgreSQL deletes dependent rows automatically.
2. **ORM:** `relationship(..., passive_deletes=True)` tells SQLAlchemy **not** to delete related objects through Python (no extra SELECT + DELETE per row) and to trust the DB instead.

**Why:**
- Without `passive_deletes=True`, SQLAlchemy would try to load children/employees and delete them one by one on `db.delete(dept)` → extra queries; in async this also risks lazy-load issues.
- With `passive_deletes=True` + `ON DELETE CASCADE`, deletion is efficient and atomic on the DB side.

So `await db.delete(dept)` in the service deletes one department row; the DB handles the rest. In reassign mode the employee transfer is done with an explicit `UPDATE` **before** the delete.

---

## 8. Name uniqueness

**Decision:** department names are unique **within the same parent**, enforced in the service layer.

**Why not a DB UNIQUE constraint on `(name, parent_id)`:**
- Root departments have `parent_id = NULL`. In PostgreSQL `NULL != NULL`, so a unique index on `(name, parent_id)` **would not prevent** two root departments with the same name.
- A `UNIQUE` on `COALESCE(parent_id, 0)` would work, but the service-layer approach was chosen — it is simpler and produces a clear error message.

**Implementation:** `_check_name_unique` does a SELECT before insert/update; plus a `try/except IntegrityError` as a safety net against race conditions (concurrent requests).

---

## 9. Async, sessions, get_db

**Decision:** fully async DB access (`asyncpg` + `AsyncSession`), one session per request via a FastAPI dependency.

```python
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
```

- **engine** — connection pool, created once for the entire application.
- **AsyncSessionLocal** — session factory.
- **get_db** — dependency that yields one session per HTTP request.

**Why `async with` + `yield`:**
- `async with` guarantees the session is closed and the connection returned to the pool — on success and on error (equivalent to `try/finally`).
- `yield` hands the session to the router and keeps `async with` open for the duration of the request. After the endpoint returns (or raises), FastAPI **resumes** the generator past `yield` → `__aexit__` fires → session closes.
- The connection is released **at the end** of the request, not during it — which is correct (otherwise the session would close before commit).
- The teardown guarantee is provided by **FastAPI** (lifecycle dependency), not the context manager alone.

**Why async at all:** FastAPI is async; while a request waits for PostgreSQL, the event loop can serve other requests. A synchronous driver would block the server.

**No lazy loading:** all relationships are loaded explicitly via `select()` — to avoid N+1 queries and lazy-load errors in async.

---

## 10. expire_on_commit

**Decision:** `expire_on_commit=False` in the session factory.

**What it is:** by default (`True`), after `commit()` SQLAlchemy marks all ORM objects as expired — accessing any attribute triggers a new SELECT. With `False`, attributes remain accessible without hitting the DB.

**Why it matters here:**
- In the router, after the service returns, `DepartmentBase.model_validate(dept)` reads `dept.id`, `dept.name`, etc.
- With `expire_on_commit=True` this would trigger a lazy reload after commit; in async that means an extra query or an error (if the session is already closing).
- With `False`, reading attributes is a plain Python attribute access.

**What this does NOT mean:**
- This is **not a database snapshot**. It preserves already-loaded fields of **one** ORM object in memory.
- If another request modifies the same row, the in-memory object will not update automatically.

**Relation to `refresh`:** `db.refresh(dept)` after commit pulls in server-generated defaults (`id`, `created_at`). `expire_on_commit=False` ensures those values remain accessible when building the response.

---

## 11. Configuration and environments

**Decision:** `pydantic-settings`; `DATABASE_URL` read from the environment with a code-level default.

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/department_api"
    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
```

- Priority: environment variable → `.env` → code default.
- `extra: "ignore"` — unknown environment variables do not break loading.
- `settings = Settings()` — a module-level instance (effectively a singleton via the import cache; **not** the Singleton pattern).

**On duplicated URLs (local vs Docker):**
- Locally the DB host is `localhost`; in Docker it is the `db` service inside the compose network. Hence the different URLs.
- In compose, `DATABASE_URL` is set directly in `environment`; `.env` is not copied into the production image.
- Credentials are repeated in several places (`config.py` default, `.env`, `docker-compose.yml`) — acceptable for a test project; in production it is better to construct the URL from parts (`${POSTGRES_USER}` etc.) to have a single source of truth.

---

## 12. SQLAlchemy 2.0: new syntax

**Decision:** typed mappings — `Mapped[...]` + `mapped_column(...)`.

```python
id: Mapped[int] = mapped_column(Integer, primary_key=True)
parent_id: Mapped[int | None] = mapped_column(ForeignKey(...), nullable=True)
employees: Mapped[list["Employee"]] = relationship(...)
```

**Why it is better than the old style (`id = Column(...)`):**
- Full typing: mypy and IDEs know the field types (`dept.parent_id` → `int | None`).
- Explicit separation of columns (`mapped_column`) and relationships (`relationship`).
- Consistent style with the rest of the 2.0 API (`select()` instead of `session.query()`).

**Clarifications:**
- This is **SQLAlchemy** syntax, not Alembic. Alembic only reads `Base.metadata`.
- SQLAlchemy 2.0 is **backwards compatible**: the old declarative syntax also works. The new style is the recommended approach, not a requirement.

**On `Base`:** a shared `DeclarativeBase` is needed so all models share one `metadata` (otherwise each has its own registry → Alembic and relationships break). It lives in `database.py` (infrastructure); models import it — the dependency direction is `models → database`, with no cycles.

---

## 13. Tests

**Decision:** integration tests against a real PostgreSQL instance in Docker.

- Dedicated DB `department_api_test`, service `db_test` (Docker Compose profile `test`).
- `conftest.py`: `alembic upgrade head` before tests, `downgrade base` after — this also validates the migrations themselves.
- `dependency_overrides[get_db]` — replaces the session with a test one (test engine/sessionmaker).
- `httpx.AsyncClient` + `ASGITransport(app=app)` — requests to the app without starting a real HTTP server.
- `TEST_DATABASE_URL` is injected by compose; locally it falls back to `localhost`.

**Why a real DB instead of mocks:** tests cover real FKs, `ON DELETE CASCADE`, `NULL` behaviour in uniqueness, and the recursive CTE — none of which can be reliably mocked.
