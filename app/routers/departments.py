from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    CycleDetectedError,
    DepartmentNotFoundError,
    DuplicateDepartmentNameError,
    InvalidDeleteModeError,
    InvalidReassignTargetError,
    ReassignTargetNotFoundError,
    SelfParentReferenceError,
)
from app.schemas import (
    DepartmentBase,
    DepartmentCreate,
    DepartmentTreeResponse,
    DepartmentUpdate,
)
from app.services import departments as svc

router = APIRouter()


@router.post(
    "/",
    response_model=DepartmentBase,
    status_code=201,
    summary="Create department",
    description=(
        "Creates a new department. "
        "The name is stripped of whitespace and must be unique within the same parent. "
        "Pass `parent_id: null` (or omit it) to create a root department."
    ),
    responses={
        404: {"description": "Parent department not found"},
        409: {"description": "Duplicate name within the same parent"},
    },
)
async def create_department(
    data: DepartmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DepartmentBase:
    try:
        dept = await svc.create_department(db, data)
        return DepartmentBase.model_validate(dept)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateDepartmentNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{dept_id}",
    response_model=DepartmentTreeResponse,
    summary="Get department",
    description=(
        "Returns a department with its employees and a nested subtree "
        "of child departments. "
        "`depth` controls how many levels of children are returned (1–5). "
        "Set `include_employees=false` to omit the employee list "
        "of the requested department from the response."
    ),
    responses={
        404: {"description": "Department not found"},
    },
)
async def get_department(
    dept_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    depth: Annotated[
        int, Query(ge=1, le=5, description="Number of child levels to include")
    ] = 1,
    include_employees: Annotated[
        bool, Query(description="Include employees in the response")
    ] = True,
    sort_employees_by: Annotated[
        Literal["created_at", "full_name"],
        Query(description="Field to sort employees by"),
    ] = "created_at",
) -> DepartmentTreeResponse:
    try:
        return await svc.get_department_tree(
            db, dept_id, depth, include_employees, sort_employees_by
        )
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/{dept_id}",
    response_model=DepartmentBase,
    summary="Update department",
    description=(
        "Partially updates a department. Both fields are optional — "
        "only provided fields are changed. "
        "To move the department to the root, explicitly pass `parent_id: null`. "
        "A move is rejected if it would create a cycle in the department tree."
    ),
    responses={
        400: {"description": "Department cannot be its own parent"},
        404: {"description": "Department or new parent not found"},
        409: {"description": "Name conflict or cycle detected"},
    },
)
async def update_department(
    dept_id: int,
    data: DepartmentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DepartmentBase:
    try:
        dept = await svc.update_department(db, dept_id, data)
        return DepartmentBase.model_validate(dept)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfParentReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CycleDetectedError, DuplicateDepartmentNameError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/{dept_id}",
    status_code=204,
    summary="Delete department",
    description=(
        "Deletes a department in one of two modes:\n\n"
        "- **cascade** — deletes the department, all child departments recursively, "
        "and all their employees.\n"
        "- **reassign** — moves the direct employees of this department to "
        "`reassign_to_department_id`, then deletes the department "
        "(child departments and their employees are still deleted by cascade). "
        "The reassign target cannot be the department itself"
        " or one of its descendants.\n\n"
        "`reassign_to_department_id` is required when `mode=reassign`."
    ),
    responses={
        204: {"description": "Department deleted"},
        400: {
            "description": "reassign_to_department_id is missing "
            "or is the department being deleted / one of its descendants"
        },
        404: {"description": "Department or reassign target not found"},
    },
)
async def delete_department(
    dept_id: int,
    mode: Annotated[Literal["cascade", "reassign"], Query(description="Deletion mode")],
    db: Annotated[AsyncSession, Depends(get_db)],
    reassign_to_department_id: Annotated[
        int | None,
        Query(description="Target department ID (required when mode=reassign)"),
    ] = None,
) -> Response:
    try:
        await svc.delete_department(db, dept_id, mode, reassign_to_department_id)
        return Response(status_code=204)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDeleteModeError, InvalidReassignTargetError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReassignTargetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
