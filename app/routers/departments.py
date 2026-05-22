import logging
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

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    response_model=DepartmentBase,
    status_code=201,
    summary="Создать отдел",
    description=(
        "Создаёт новый отдел. "
        "Название обрезается и должно быть уникальным в пределах одного родителя. "
        "Передайте `parent_id: null` (или не указывайте), "
        "чтобы создать корневой отдел."
    ),
    responses={
        404: {"description": "Родительский отдел не найден"},
        409: {"description": "Дублирующееся название в пределах одного родителя"},
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
    summary="Получить данные отдела",
    description=(
        "Возвращает отдел с его сотрудниками и вложенным поддеревом "
        "дочерних отделов. "
        "`depth` задаёт количество уровней вложенности дочерних отделов (1–5). "
        "Установите `include_employees=false`, "
        "чтобы исключить списки сотрудников со всех уровней."
    ),
    responses={
        404: {"description": "Отдел не найден"},
    },
)
async def get_department(
    dept_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    depth: Annotated[
        int, Query(ge=1, le=5, description="Глубина вложенности дочерних отделов")
    ] = 1,
    include_employees: Annotated[
        bool, Query(description="Включить сотрудников в ответ")
    ] = True,
    sort_employees_by: Annotated[
        Literal["created_at", "full_name"],
        Query(description="Поле для сортировки сотрудников"),
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
    summary="Обновить отдел",
    description=(
        "Частично обновляет отдел. Оба поля необязательны — "
        "изменяются только переданные поля. "
        "Чтобы переместить отдел в корень, явно передайте `parent_id: null`. "
        "Перемещение отклоняется, если создаёт цикл в дереве отделов."
    ),
    responses={
        400: {"description": "Отдел не может быть своим собственным родителем"},
        404: {"description": "Отдел или новый родитель не найден"},
        409: {"description": "Конфликт имён или обнаружен цикл"},
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
    summary="Удалить отдел",
    description=(
        "Удаляет отдел в одном из двух режимов:\n\n"
        "- **cascade** — удаляет отдел, все дочерние отделы рекурсивно "
        "и всех их сотрудников.\n"
        "- **reassign** — перемещает прямых сотрудников этого отдела в "
        "`reassign_to_department_id`, затем удаляет отдел "
        "(дочерние отделы и их сотрудники всё равно каскадно удаляются). "
        "Цель переназначения не может быть самим удаляемым отделом "
        "или его потомком.\n\n"
        "`reassign_to_department_id` обязателен при `mode=reassign`."
    ),
    responses={
        204: {"description": "Отдел удалён"},
        400: {
            "description": "reassign_to_department_id отсутствует "
            "или является удаляемым отделом / его потомком"
        },
        404: {"description": "Отдел или цель переназначения не найдены"},
    },
)
async def delete_department(
    dept_id: int,
    mode: Annotated[
        Literal["cascade", "reassign"], Query(description="Режим удаления")
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    reassign_to_department_id: Annotated[
        int | None,
        Query(description="ID целевого отдела (обязателен при mode=reassign)"),
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
