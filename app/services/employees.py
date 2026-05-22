import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DepartmentNotFoundError
from app.models import Department, Employee
from app.schemas import EmployeeCreate

logger = logging.getLogger(__name__)


async def create_employee(
    db: AsyncSession, dept_id: int, data: EmployeeCreate
) -> Employee:
    """Create a new employee in the specified department."""
    if await db.get(Department, dept_id) is None:
        raise DepartmentNotFoundError(dept_id)

    employee = Employee(
        department_id=dept_id,
        full_name=data.full_name,
        position=data.position,
        hired_at=data.hired_at,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    logger.info("Created employee id=%d in department id=%d", employee.id, dept_id)
    return employee
