import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import get_db
from main import app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/department_api_test",
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(command: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL
    subprocess.run(
        ["uv", "run", "alembic", command, revision],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


@pytest.fixture
def migrated_database() -> AsyncIterator[None]:
    _run_alembic("upgrade", "head")
    yield
    _run_alembic("downgrade", "base")


@pytest_asyncio.fixture
async def db_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
