from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import (
    CycleDetectedError,
    DepartmentNotFoundError,
    DuplicateDepartmentNameError,
    InvalidDeleteModeError,
    InvalidReassignTargetError,
    ReassignTargetNotFoundError,
    SelfParentReferenceError,
)

_STATUS_BY_EXCEPTION: dict[type[Exception], int] = {
    DepartmentNotFoundError: 404,
    ReassignTargetNotFoundError: 404,
    SelfParentReferenceError: 400,
    InvalidDeleteModeError: 400,
    InvalidReassignTargetError: 400,
    DuplicateDepartmentNameError: 409,
    CycleDetectedError: 409,
}


async def _handle_domain_exception(request: Request, exc: Exception) -> JSONResponse:
    status_code = _STATUS_BY_EXCEPTION[type(exc)]
    return JSONResponse({"detail": str(exc)}, status_code=status_code)


def register_exception_handlers(app: FastAPI) -> None:
    """Map each domain exception to its HTTP status, replacing per-router try/except."""
    for exc_type in _STATUS_BY_EXCEPTION:
        app.add_exception_handler(exc_type, _handle_domain_exception)
