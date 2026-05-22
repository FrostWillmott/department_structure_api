# Department Structure API

REST API for managing organizational structure: hierarchical departments and employees.

## Tech stack

- **FastAPI** — async web framework
- **SQLAlchemy 2.0** (async) + **asyncpg** — database access
- **PostgreSQL 16** — primary database
- **Alembic** — migrations
- **pydantic-settings** — configuration
- **ruff** + **mypy** — linting and type checking
- **pytest** + **pytest-asyncio** + **httpx** — testing

## Quick start

```bash
docker-compose up --build
```

The application will be available at [http://localhost:8000](http://localhost:8000).  
Interactive API documentation: [http://localhost:8000/docs](http://localhost:8000/docs).

Migrations run automatically on container startup.

## Local development

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL running on localhost:5432.

```bash
# Install dependencies
uv sync --extra dev

# Setup pre-commit hooks
uv run pre-commit install

# Configure database URL
cp .env.example .env
# Edit .env if needed

# Run migrations
uv run alembic upgrade head

# Start dev server
uv run uvicorn main:app --reload
```

## Running tests

Tests run in Docker against a dedicated PostgreSQL instance — no local setup required:

```bash
docker compose --profile test up --build --abort-on-container-exit --exit-code-from test
```

Coverage report is printed in the container output.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api` | Async PostgreSQL connection URL |
| `TEST_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api_test` | Test database URL (set automatically in Docker) |

## API overview

| Method | Path | Description |
|---|---|---|
| `POST` | `/departments/` | Create a department |
| `GET` | `/departments/{id}` | Get department with employees and subtree |
| `PATCH` | `/departments/{id}` | Rename or move a department |
| `DELETE` | `/departments/{id}` | Delete (cascade or reassign mode) |
| `POST` | `/departments/{id}/employees/` | Add an employee to a department |

### Key behaviours

- Department names are **unique within the same parent** scope.
- Moving a department is rejected if it would create a **cycle** in the tree.
- `GET /departments/{id}` accepts `depth` (1–5), `include_employees`, and `sort_employees_by` query parameters.
- `DELETE` with `mode=cascade` removes the department, all child departments, and all their employees.
- `DELETE` with `mode=reassign` moves the department's direct employees to `reassign_to_department_id` before deletion.
