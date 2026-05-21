import logging
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import (
    CycleDetectedError,
    DepartmentNotFoundError,
    DuplicateDepartmentNameError,
    InvalidDeleteModeError,
    ReassignTargetNotFoundError,
    SelfParentReferenceError,
)
from app.models import Department, Employee
from app.schemas import (
    DepartmentCreate,
    DepartmentDetail,
    DepartmentUpdate,
    EmployeeCreate,
    EmployeeResponse,
)

logger = logging.getLogger(__name__)


async def _get_descendants_ids(db: AsyncSession, dept_id: int) -> set[int]:
    result: set[int] = set()
    queue = [dept_id]
    while queue:
        rows = await db.execute(
            select(Department.id).where(Department.parent_id.in_(queue))
        )
        queue = []
        for (child_id,) in rows:
            result.add(child_id)
            queue.append(child_id)
    return result


async def _check_name_unique(
    db: AsyncSession,
    name: str,
    parent_id: int | None,
    exclude_id: int | None = None,
) -> None:
    stmt = select(Department).where(
        Department.name == name,
        Department.parent_id == parent_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(Department.id != exclude_id)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none() is not None:
        raise DuplicateDepartmentNameError(name, parent_id)


async def create_department(db: AsyncSession, data: DepartmentCreate) -> Department:
    """Create a new department, validating parent existence and name uniqueness."""
    if data.parent_id is not None:
        if await db.get(Department, data.parent_id) is None:
            raise DepartmentNotFoundError(data.parent_id)

    await _check_name_unique(db, data.name, data.parent_id)

    dept = Department(name=data.name, parent_id=data.parent_id)
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    logger.info(
        "Created department id=%d name=%r parent_id=%s",
        dept.id,
        dept.name,
        dept.parent_id,
    )
    return dept


async def get_department_tree(
    db: AsyncSession,
    dept_id: int,
    depth: int,
    include_employees: bool,
    sort_by: Literal["created_at", "full_name"],
) -> DepartmentDetail:
    """Return a department with nested children and optional employee lists."""
    stmt = select(Department).where(Department.id == dept_id)
    if include_employees:
        stmt = stmt.options(selectinload(Department.employees))
    row = await db.execute(stmt)
    dept = row.scalar_one_or_none()
    if dept is None:
        raise DepartmentNotFoundError(dept_id)

    employees: list[EmployeeResponse] = []
    if include_employees:
        sorted_employees = sorted(dept.employees, key=lambda e: getattr(e, sort_by))
        employees = [EmployeeResponse.model_validate(e) for e in sorted_employees]

    children: list[DepartmentDetail] = []
    if depth > 0:
        child_rows = await db.execute(
            select(Department).where(Department.parent_id == dept_id)
        )
        for child in child_rows.scalars().all():
            children.append(
                await get_department_tree(
                    db, child.id, depth - 1, include_employees, sort_by
                )
            )

    return DepartmentDetail(
        id=dept.id,
        name=dept.name,
        parent_id=dept.parent_id,
        created_at=dept.created_at,
        employees=employees,
        children=children,
    )


async def update_department(
    db: AsyncSession, dept_id: int, data: DepartmentUpdate
) -> Department:
    """Rename or reparent a department, rejecting self-references and cycles."""
    dept = await db.get(Department, dept_id)
    if dept is None:
        raise DepartmentNotFoundError(dept_id)

    effective_parent_id = dept.parent_id

    if "parent_id" in data.model_fields_set:
        new_parent_id = data.parent_id
        if new_parent_id == dept_id:
            raise SelfParentReferenceError()
        if new_parent_id is not None:
            if await db.get(Department, new_parent_id) is None:
                raise DepartmentNotFoundError(new_parent_id)
        descendants = await _get_descendants_ids(db, dept_id)
        if new_parent_id in descendants:
            raise CycleDetectedError()
        dept.parent_id = new_parent_id
        effective_parent_id = new_parent_id

    if "name" in data.model_fields_set and data.name is not None:
        await _check_name_unique(db, data.name, effective_parent_id, exclude_id=dept_id)
        dept.name = data.name

    await db.commit()
    await db.refresh(dept)
    logger.info("Updated department id=%d", dept_id)
    return dept


async def delete_department(
    db: AsyncSession,
    dept_id: int,
    mode: Literal["cascade", "reassign"],
    reassign_to_id: int | None,
) -> None:
    """Delete a department in cascade or reassign mode."""
    dept = await db.get(Department, dept_id)
    if dept is None:
        raise DepartmentNotFoundError(dept_id)

    if mode == "reassign":
        if reassign_to_id is None:
            raise InvalidDeleteModeError()
        if await db.get(Department, reassign_to_id) is None:
            raise ReassignTargetNotFoundError(reassign_to_id)
        await db.execute(
            update(Employee)
            .where(Employee.department_id == dept_id)
            .values(department_id=reassign_to_id)
        )

    await db.delete(dept)
    await db.commit()
    logger.info("Deleted department id=%d mode=%s", dept_id, mode)


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
