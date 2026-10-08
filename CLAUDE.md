# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

REST API for managing organizational structure (departments + employees). Test assignment. Stack: FastAPI, async SQLAlchemy 2.0 + asyncpg, PostgreSQL, Alembic, Docker.

## Commands

Package manager: `uv`. All commands go through it.

```bash
# Install all deps including dev
uv sync --extra dev

# Setup pre-commit hooks (once after clone)
uv run pre-commit install

# Run dev server
uv run uvicorn main:app --reload

# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy .

# Run tests in Docker (recommended — no local postgres needed)
docker compose --profile test up --build --abort-on-container-exit --exit-code-from test

# Run tests locally (requires postgres with department_api_test DB)
uv run pytest

# Run a single test
uv run pytest tests/test_api.py::test_create_department -v

# Migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Start full stack
docker compose up --build
```

## Architecture

Three-layer architecture:

```
routers/    → HTTP only: parse request, call service, return response
services/   → Business logic: validation, cycle detection, cascade rules
database.py → AsyncSession factory via get_db() dependency
```

Services raise domain exceptions (`app/exceptions.py`). `app/error_handlers.py` maps them to HTTP status codes in one place (registered in `main.py`); routers don't catch them. Services have no knowledge of HTTP.

```
app/
├── config.py        # pydantic-settings, reads DATABASE_URL from env
├── database.py      # async_engine, AsyncSessionLocal, get_db()
├── models.py        # SQLAlchemy ORM: Department, Employee
├── schemas.py       # Pydantic DTOs; field validators strip whitespace
├── exceptions.py    # Domain exceptions (DepartmentNotFound, CycleDetected, …)
├── error_handlers.py # Domain exception → HTTP status mapping
├── routers/
│   ├── departments.py
│   └── employees.py
└── services/
    ├── _pg.py       # SQLSTATE extraction from asyncpg IntegrityError
    ├── departments.py
    └── employees.py
```

## Key design decisions

**Async**: all DB access uses `AsyncSession`. Never use lazy loading — always load relationships explicitly with `selectinload` in the query.

**Self-referential tree**: `Department.parent_id` FK has `ON DELETE CASCADE`. Deleting a parent cascades to children at DB level. Employee FK also `ON DELETE CASCADE`.

**Cycle detection** (PATCH /departments/{id}): before updating `parent_id`, fetch all descendants via BFS, check that the new parent is not among them.

**DepartmentUpdate PATCH**: uses `model_fields_set` to distinguish "field not provided" from "field explicitly set to null" (null = move department to root).

**Unique name constraint**: scoped per `parent_id`. Enforced at two levels: DB partial unique indexes (`uq_departments_name_parent`/`uq_departments_name_root`, splitting on `parent_id IS NULL` to work around NULL != NULL) are the source of truth; a service-layer pre-check (`_check_name_unique`) gives a readable 409 instead of a raw constraint violation, with an `IntegrityError` fallback for the race between check and commit.

## Tests

Tests run against a dedicated PostgreSQL instance (`db_test`) via Docker Compose profiles. `TEST_DATABASE_URL` is injected by docker-compose; locally it falls back to `localhost:5432/department_api_test`. The conftest runs `alembic upgrade head` once per session (and `downgrade base` once at the end), then truncates all tables before each test.

## Code style

- `ruff` for linting and formatting (replaces black + flake8)
- `mypy` strict mode (adjust if blocking, document why)
- `pre-commit` runs ruff + mypy on every commit
- No repository layer — services call SQLAlchemy directly
- No comments unless the why is non-obvious
- All string inputs stripped of whitespace via Pydantic `field_validator(..., mode='before')`
