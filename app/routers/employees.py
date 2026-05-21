import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DepartmentNotFoundError
from app.schemas import EmployeeCreate, EmployeeResponse
from app.services import departments as svc

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{dept_id}/employees/",
    response_model=EmployeeResponse,
    status_code=201,
    summary="Add an employee to a department",
    description=(
        "Creates a new employee in the specified department. "
        "Both `full_name` and `position` are trimmed and must be non-empty. "
        "`hired_at` is optional."
    ),
    responses={
        404: {"description": "Department not found"},
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
