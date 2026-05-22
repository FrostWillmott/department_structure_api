# Technical Decisions

Non-obvious design choices made in this project, with rationale.

---

## Overall approach

### Clean architecture without over-engineering

A common mistake on test assignments is adding abstractions for their own sake — repository interfaces, service protocols, generic base classes, factories. These signal familiarity with patterns but raise the question of whether the author understands *when* to apply them. The rule applied here: add a layer only when it solves a concrete problem visible in the current codebase. Every layer that exists (router → service → ORM) has a clear reason; everything considered and rejected (repository, generic CRUD mixin) was left out because the project doesn't need it yet.

---

## Architecture

### No repository layer

Services call SQLAlchemy `AsyncSession` directly. A repository layer would add an abstraction boundary between service logic and the ORM — useful when you need to swap storage backends or isolate SQL from business logic in large codebases. Here the storage is a fixed PostgreSQL, the service layer is already thin, and the extra indirection would obscure more than it clarifies.

### Domain exceptions, no HTTP in services

Services raise typed domain exceptions (`DepartmentNotFound`, `CycleDetected`, etc.). Routers catch them and convert to `HTTPException`. This means service functions are testable without an HTTP context, and the mapping from business error to status code lives in one place (the router), not scattered through business logic.

---

## Database / ORM

### Name uniqueness enforced in the service layer, not via DB constraint

A `UNIQUE(name, parent_id)` index would seem natural, but NULL values break it: SQL treats `NULL != NULL`, so two root-level departments (`parent_id IS NULL`) with the same name would not be caught by a unique index. The service explicitly queries `WHERE name = ? AND parent_id IS NULL` (or `= ?`), which handles both cases uniformly.

### `ON DELETE CASCADE` at DB level + `passive_deletes=True` on ORM relationships

Cascade deletion of child departments and employees is declared on the FK constraint (`ondelete="CASCADE"`), not as an ORM cascade. Without `passive_deletes=True`, SQLAlchemy doesn't know the DB will handle cascades — it issues `UPDATE employees SET department_id = NULL` before the `DELETE`, which violates the `NOT NULL` constraint on `department_id`. With `passive_deletes=True`, SQLAlchemy trusts the DB and sends only the `DELETE`.

### BFS cycle detection instead of recursive CTE

Before allowing a `parent_id` change, we walk the existing subtree with BFS (sequential `SELECT id WHERE parent_id IN (...)` rounds) to collect all descendants, then check if the new parent is among them. The alternative — a single `WITH RECURSIVE` CTE — would be more efficient for deep trees but adds SQL complexity. For typical org charts (depth < 10, hundreds of nodes) the extra round trips are negligible, and the Python code is easier to read and test.

### Reassign mode moves only direct employees

`DELETE ?mode=reassign` moves the department's *direct* employees to the target, then deletes the department. Child sub-departments and their employees are still cascade-deleted by the DB. Recursively reassigning the entire subtree was considered but rejected: a subtree reassign is a distinct operation ("reorganize") that deserves its own explicit endpoint, not a flag on delete.

### No eager/lazy loading — explicit `selectinload` at query site

SQLAlchemy async does not support lazy loading (raises `MissingGreenlet`). All relationship loads use `selectinload` at the point of the query that needs them, so it is always clear which SQL is executed and when. Relationships on the model have no `lazy=` setting to avoid accidentally enabling implicit loading.

---

## Test infrastructure

### Function-scoped `db_engine` fixture (create/drop tables per test)

A session-scoped engine would be faster, but pytest-asyncio assigns a separate event loop per test function. An engine created in one event loop cannot be safely used from another — asyncpg's connection pool is bound to the loop it was created in. The per-test create/drop is a few milliseconds overhead per test and eliminates this class of failures entirely.

### `from main import app` at module level in conftest.py

`Base.metadata` only knows about tables whose model classes have been imported. `conftest.py` imports `from app.database import Base` but not `app.models`. If `from main import app` is deferred to inside the `client` fixture (which runs *after* `db_engine`), then `Base.metadata.create_all` runs on an empty registry and creates no tables — the first test fails with `UndefinedTableError`, the second passes because `app.models` was imported by then. Moving the import to module level ensures models are registered before any fixture executes.

---

## Docker

### Multi-stage Dockerfile (`base` → `production` / `test`)

The `production` stage copies only `app/`, `alembic/`, `alembic.ini`, and `main.py` — no tests, no dev dependencies. The `test` stage (`COPY . .`) includes everything. A single-stage image that included test files and dev deps in production was rejected: it leaks internal tooling into the deployed artefact and inflates the image size.

### Docker Compose profiles for test isolation

The `db_test` and `test` services are in the `test` profile. `docker compose up` starts the app stack; `docker compose --profile test up` runs tests. This is the idiomatic Compose pattern for optional service groups and avoids maintaining separate compose files (`docker-compose.prod.yml`, `docker-compose.test.yml`) that drift out of sync.
