"""Unit tests for service-layer race-condition handlers that can't be
triggered through the API alone — they require mocking db.commit() to simulate
concurrent transactions.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.exceptions import DepartmentNotFoundError, DuplicateDepartmentNameError
from app.models import Department
from app.schemas import DepartmentCreate, DepartmentUpdate, EmployeeCreate
from app.services.departments import create_department, update_department
from app.services.employees import create_employee

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

UNIQUE_SQLSTATE = "23505"
FK_SQLSTATE = "23503"
BOGUS_SQLSTATE = "99999"


def _integrity_error(sqlstate: str) -> IntegrityError:
    """Build an IntegrityError whose ``orig.__cause__`` carries *sqlstate*."""
    cause = MagicMock(sqlstate=sqlstate)
    orig = MagicMock(__cause__=cause)
    return IntegrityError("stmt", params={}, orig=orig)


def _make_db(*, get_returns=None, execute_scalar_returns=None):
    """Return an AsyncMock pre-configured for the common session usage.

    ``get_returns`` is a list (or single value) returned sequentially by
    ``await db.get(...)``.  ``execute_scalar_returns`` is a list (or single
    value) returned by ``db.execute(...).scalar_one_or_none()``.
    """
    db = AsyncMock()

    # db.add() is synchronous — swap the auto-generated AsyncMock method.
    db.add = MagicMock()

    # db.get()  (used for existence checks)
    if get_returns is None:
        get_returns = []
    elif not isinstance(get_returns, list):
        get_returns = [get_returns]
    db.get.side_effect = get_returns

    # db.execute() → .scalar_one_or_none()  (_check_name_unique)
    if execute_scalar_returns is None:
        execute_scalar_returns = []
    elif not isinstance(execute_scalar_returns, list):
        execute_scalar_returns = [execute_scalar_returns]

    class _ExecResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def __iter__(self):
            # For execute() calls that iterate rows (BFS)
            return iter([])

        def all(self):
            return []

    exec_results = [_ExecResult(v) for v in execute_scalar_returns]
    db.execute.side_effect = exec_results if exec_results else [None]

    return db


# ---------------------------------------------------------------------------
# create_department — IntegrityError paths  (lines 86-93)
# ---------------------------------------------------------------------------


async def test_create_department_integrity_error_unique_violation():
    """Duplicate name inserted between pre-check and commit → 409."""
    db = _make_db(
        get_returns=[Department(id=5, name="Parent", parent_id=None)],  # parent exists
        execute_scalar_returns=[None],  # _check_name_unique: no duplicate
    )
    db.commit.side_effect = _integrity_error(UNIQUE_SQLSTATE)

    with pytest.raises(DuplicateDepartmentNameError):
        await create_department(db, DepartmentCreate(name="X", parent_id=5))

    db.rollback.assert_awaited_once()


async def test_create_department_integrity_error_fk_violation():
    """Parent deleted between pre-check and commit → 404."""
    db = _make_db(
        get_returns=[Department(id=5, name="Parent", parent_id=None)],
        execute_scalar_returns=[None],
    )
    db.commit.side_effect = _integrity_error(FK_SQLSTATE)

    with pytest.raises(DepartmentNotFoundError):
        await create_department(db, DepartmentCreate(name="X", parent_id=5))

    db.rollback.assert_awaited_once()


async def test_create_department_integrity_error_unexpected():
    """An IntegrityError with unknown sqlstate is re-raised."""
    db = _make_db(
        get_returns=[Department(id=5, name="Parent", parent_id=None)],
        execute_scalar_returns=[None],
    )
    db.commit.side_effect = _integrity_error(BOGUS_SQLSTATE)

    with pytest.raises(IntegrityError, match="stmt"):
        await create_department(db, DepartmentCreate(name="X", parent_id=5))

    db.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# update_department — IntegrityError + StaleDataError paths  (lines 222-236)
# ---------------------------------------------------------------------------


async def test_update_department_integrity_error_unique_violation():
    """Rename collides with a concurrent insert → 409."""
    dept = Department(id=1, name="Old", parent_id=None)
    db = _make_db(
        get_returns=[dept],  # department found
        execute_scalar_returns=[None],  # _check_name_unique: name free
    )
    db.commit.side_effect = _integrity_error(UNIQUE_SQLSTATE)

    with pytest.raises(DuplicateDepartmentNameError):
        await update_department(db, 1, DepartmentUpdate(name="NewName"))

    db.rollback.assert_awaited_once()


async def test_update_department_integrity_error_fk_violation():
    """Reparent to a department deleted between check and commit → 404."""
    dept = Department(id=1, name="Old", parent_id=None)
    new_parent = Department(id=2, name="Target", parent_id=None)
    db = _make_db(
        get_returns=[dept, new_parent],
        execute_scalar_returns=[
            None,  # _lock_tree: pg_advisory_xact_lock
            None,  # _get_descendants_ids: BFS over Department.id
            None,  # _check_name_unique
        ],
    )
    db.commit.side_effect = _integrity_error(FK_SQLSTATE)

    with pytest.raises(DepartmentNotFoundError):
        await update_department(db, 1, DepartmentUpdate(parent_id=2))

    db.rollback.assert_awaited_once()


async def test_update_department_stale_data_error():
    """Rename-only update when department is deleted concurrently → 404."""
    dept = Department(id=1, name="Old", parent_id=None)
    db = _make_db(
        get_returns=[dept],
        execute_scalar_returns=[None],  # _check_name_unique
    )
    db.commit.side_effect = StaleDataError()

    with pytest.raises(DepartmentNotFoundError):
        await update_department(db, 1, DepartmentUpdate(name="NewName"))

    db.rollback.assert_awaited_once()


async def test_update_department_integrity_error_unexpected():
    """An IntegrityError with unknown sqlstate on update is re-raised."""
    dept = Department(id=1, name="Old", parent_id=None)
    db = _make_db(
        get_returns=[dept],
        execute_scalar_returns=[None],  # _check_name_unique
    )
    db.commit.side_effect = _integrity_error(BOGUS_SQLSTATE)

    with pytest.raises(IntegrityError, match="stmt"):
        await update_department(db, 1, DepartmentUpdate(name="NewName"))

    db.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# create_employee — IntegrityError paths  (lines 31-37)
# ---------------------------------------------------------------------------


async def test_create_employee_integrity_error_fk_violation():
    """Department deleted between existence check and insert commit → 404."""
    db = _make_db(
        get_returns=[Department(id=1, name="Eng", parent_id=None)],
    )
    db.commit.side_effect = _integrity_error(FK_SQLSTATE)

    with pytest.raises(DepartmentNotFoundError):
        await create_employee(db, 1, EmployeeCreate(full_name="A B", position="Dev"))

    db.rollback.assert_awaited_once()


async def test_create_employee_integrity_error_unexpected():
    """An IntegrityError with unknown sqlstate on employee insert is re-raised."""
    db = _make_db(
        get_returns=[Department(id=1, name="Eng", parent_id=None)],
    )
    db.commit.side_effect = _integrity_error(BOGUS_SQLSTATE)

    with pytest.raises(IntegrityError, match="stmt"):
        await create_employee(db, 1, EmployeeCreate(full_name="A B", position="Dev"))

    db.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_db  (lines 25-26)
# ---------------------------------------------------------------------------


async def test_get_db_yields_session():
    """get_db() is an async generator that yields an AsyncSession."""
    from unittest.mock import patch

    from app.database import get_db

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__ = AsyncMock()

    with patch("app.database.AsyncSessionLocal", mock_factory):
        gen = get_db()
        session = await gen.__anext__()
        assert session is mock_session
