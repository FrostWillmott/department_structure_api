import logging
from typing import Literal

from sqlalchemy import literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    CycleDetectedError,
    DepartmentNotFoundError,
    DuplicateDepartmentNameError,
    InvalidDeleteModeError,
    InvalidReassignTargetError,
    ReassignTargetNotFoundError,
    SelfParentReferenceError,
)
from app.models import Department, Employee
from app.schemas import (
    DepartmentBase,
    DepartmentCreate,
    DepartmentTreeNode,
    DepartmentTreeResponse,
    DepartmentUpdate,
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
            if child_id not in result:
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
    try:
        await db.commit()
        await db.refresh(dept)
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateDepartmentNameError(data.name, data.parent_id) from exc
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
) -> DepartmentTreeResponse:
    """Return department details, employees and nested child departments."""
    base = (
        select(
            Department.id,
            Department.name,
            Department.parent_id,
            Department.created_at,
            literal(0).label("level"),
        )
        .where(Department.id == dept_id)
        .cte(name="tree", recursive=True)
    )
    recursive_part = (
        select(
            Department.id,
            Department.name,
            Department.parent_id,
            Department.created_at,
            (base.c.level + 1).label("level"),
        )
        .join(base, Department.parent_id == base.c.id)
        .where(base.c.level < depth)
    )
    cte = base.union_all(recursive_part)
    rows = (await db.execute(select(cte).order_by(cte.c.name))).all()
    if not rows:
        raise DepartmentNotFoundError(dept_id)

    dept_map: dict[int, DepartmentTreeNode] = {
        row.id: DepartmentTreeNode(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            created_at=row.created_at,
        )
        for row in rows
    }
    employees: list[EmployeeResponse] = []

    if include_employees:
        sort_col = (
            Employee.created_at if sort_by == "created_at" else Employee.full_name
        )
        emp_rows = await db.execute(
            select(Employee).where(Employee.department_id == dept_id).order_by(sort_col)
        )
        employees = [EmployeeResponse.model_validate(emp) for emp in emp_rows.scalars()]

    for row in rows:
        if row.parent_id in dept_map and row.id != dept_id:
            dept_map[row.parent_id].children.append(dept_map[row.id])

    root = dept_map[dept_id]
    return DepartmentTreeResponse(
        department=DepartmentBase(
            id=root.id,
            name=root.name,
            parent_id=root.parent_id,
            created_at=root.created_at,
        ),
        employees=employees,
        children=root.children,
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
        if "name" not in data.model_fields_set:
            await _check_name_unique(db, dept.name, new_parent_id, exclude_id=dept_id)
        dept.parent_id = new_parent_id
        effective_parent_id = new_parent_id

    if "name" in data.model_fields_set and data.name is not None:
        await _check_name_unique(db, data.name, effective_parent_id, exclude_id=dept_id)
        dept.name = data.name

    name_to_commit = dept.name
    parent_to_commit = dept.parent_id
    try:
        await db.commit()
        await db.refresh(dept)
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateDepartmentNameError(name_to_commit, parent_to_commit) from exc
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
        if reassign_to_id == dept_id:
            raise InvalidReassignTargetError()
        if await db.get(Department, reassign_to_id) is None:
            raise ReassignTargetNotFoundError(reassign_to_id)
        descendants = await _get_descendants_ids(db, dept_id)
        if reassign_to_id in descendants:
            raise InvalidReassignTargetError()
        await db.execute(
            update(Employee)
            .where(Employee.department_id == dept_id)
            .values(department_id=reassign_to_id)
        )

    # passive_deletes=True: не трогаем Employee через ORM, каскад на стороне БД.
    await db.delete(dept)
    await db.commit()
    logger.info("Deleted department id=%d mode=%s", dept_id, mode)
