# Department Structure API

REST API for managing organizational structure: hierarchical departments and employees.

## Technologies

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

The app will be available at [http://localhost:8000](http://localhost:8000).  
Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Migrations run automatically when the container starts.

## Local development

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL on localhost:5432.

```bash
# Install dependencies
uv sync --extra dev

# Install pre-commit hooks
uv run pre-commit install

# Configure the database URL
cp .env.example .env
# Edit .env if needed

# Run migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn main:app --reload
```

## Running tests

Tests run in Docker against a dedicated PostgreSQL instance — no local setup required:

```bash
docker compose --profile test up --build --abort-on-container-exit --exit-code-from test
```

The coverage report is printed in the container logs.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api` | DB URL for running the app and migrations locally |
| `TEST_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api_test` | DB URL for running tests locally |
| `COMPOSE_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/department_api` | DB URL for the `app` service inside `docker compose` |
| `COMPOSE_TEST_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db_test:5432/department_api_test` | DB URL for the `test` service inside `docker compose --profile test` |

## API overview

| Method | Path | Description |
|---|---|---|
| `POST` | `/departments/` | Create a department |
| `GET` | `/departments/{id}` | Get department with employees and subtree |
| `PATCH` | `/departments/{id}` | Rename or move a department |
| `DELETE` | `/departments/{id}` | Delete (cascade or reassign mode) |
| `POST` | `/departments/{id}/employees/` | Add an employee to a department |

### Key behaviours

- Department names are **unique within the same parent**.
- A move is rejected if it would create a **cycle** in the tree.
- `GET /departments/{id}` accepts `depth` (1–5), `include_employees`, and `sort_employees_by`, and returns:
  - `department` — data for the requested department
  - `employees` — employees of the requested department (optional, controlled by `include_employees`)
  - `children` — recursive subtree of child departments

Example `GET /departments/{id}` response:

```json
{
  "department": {
    "id": 1,
    "name": "Engineering",
    "parent_id": null,
    "created_at": "2026-05-21T10:00:00Z"
  },
  "employees": [
    {
      "id": 10,
      "department_id": 1,
      "full_name": "Ivan Ivanov",
      "position": "Backend Developer",
      "hired_at": "2024-02-01",
      "created_at": "2026-05-21T10:01:00Z"
    }
  ],
  "children": [
    {
      "id": 2,
      "name": "Platform",
      "parent_id": 1,
      "created_at": "2026-05-21T10:02:00Z",
      "children": []
    }
  ]
}
```
- `DELETE` with `mode=cascade` deletes the department, all child departments, and all their employees.
- `DELETE` with `mode=reassign` moves the direct employees to `reassign_to_department_id` before deleting.
