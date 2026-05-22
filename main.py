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
        "REST API для управления организационной структурой "
        "отделов и сотрудников. "
        "Отделы образуют древовидную иерархию через `parent_id`. "
        "Поддерживает рекурсивное получение поддеревьев, "
        "безопасные к циклам операции над деревом, "
        "а также каскадный режим и режим переназначения при удалении."
    ),
    version="1.0.0",
)

app.include_router(departments.router, prefix="/departments", tags=["Departments"])
app.include_router(employees.router, prefix="/departments", tags=["Employees"])
