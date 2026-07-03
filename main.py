import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, get_db
from app.error_handlers import register_exception_handlers
from app.routers import departments, employees

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Dispose the engine's connection pool on shutdown."""
    yield
    await engine.dispose()


app = FastAPI(
    title="Department Structure API",
    description=(
        "REST API for managing organizational structure "
        "of departments and employees. "
        "Departments form a tree hierarchy via `parent_id`. "
        "Supports recursive subtree retrieval, "
        "cycle-safe tree operations, "
        "and both cascade and reassign modes for deletion."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.include_router(departments.router, prefix="/departments", tags=["Departments"])
app.include_router(employees.router, prefix="/departments", tags=["Employees"])


@app.get("/health", tags=["Health"], summary="Health check")
async def health(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Check DB connectivity via the same session dependency the app uses."""
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
