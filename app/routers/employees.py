from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DepartmentNotFoundError
from app.schemas import EmployeeCreate, EmployeeResponse
from app.services import employees as svc

router = APIRouter()


@router.post(
    "/{dept_id}/employees/",
    response_model=EmployeeResponse,
    status_code=201,
    summary="Добавить сотрудника в отдел",
    description=(
        "Создаёт нового сотрудника в указанном отделе. "
        "Поля `full_name` и `position` обрезаются и не должны быть пустыми. "
        "`hired_at` необязателен."
    ),
    responses={
        404: {"description": "Отдел не найден"},
    },
)
async def create_employee(
    dept_id: int,
    data: EmployeeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EmployeeResponse:
    try:
        employee = await svc.create_employee(db, dept_id, data)
        return EmployeeResponse.model_validate(employee)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
