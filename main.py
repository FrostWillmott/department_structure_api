import logging

from fastapi import FastAPI

from app.routers import departments, employees

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

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
)

app.include_router(departments.router, prefix="/departments", tags=["Departments"])
app.include_router(employees.router, prefix="/departments", tags=["Employees"])
