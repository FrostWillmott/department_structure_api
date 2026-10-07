import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database import get_db
from main import app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/department_api_test",
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Alembic's env.py reads settings.database_url, so point the shared settings at
# the test database before running migrations in-process.
settings.database_url = TEST_DATABASE_URL


def _run_alembic(action: str, revision: str) -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    if action == "upgrade":
        command.upgrade(cfg, revision)
    else:
        command.downgrade(cfg, revision)


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[None]:
    _run_alembic("upgrade", "head")
    yield
    _run_alembic("downgrade", "base")


@pytest_asyncio.fixture(scope="session")
async def db_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(db_engine: AsyncEngine) -> None:
    """Isolate each test: migrations run once per session, not per test."""
    async with db_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE employees, departments RESTART IDENTITY CASCADE")
        )


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
