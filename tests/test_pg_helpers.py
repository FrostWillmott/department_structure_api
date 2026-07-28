from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import Employee
from app.services import _pg


def test_constraint_sqlstate_fallback_on_orig():
    """When orig.__cause__ exists but has no sqlstate, read orig.sqlstate directly.

    This covers the fallback at app/services/_pg.py:17.
    """
    orig = MagicMock(sqlstate="23503")
    orig.__cause__ = None  # no chained cause
    exc = IntegrityError("stmt", params={}, orig=orig)
    assert _pg.constraint_sqlstate(exc) == "23503"


def test_constraint_sqlstate_returns_none_when_not_string():
    """Non-string sqlstate attributes are treated as absent."""
    orig = MagicMock(sqlstate=23503)  # int, not str
    orig.__cause__ = None
    exc = IntegrityError("stmt", params={}, orig=orig)
    assert _pg.constraint_sqlstate(exc) is None


async def test_fk_violation_classified_correctly(db_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Employee(department_id=9999, full_name="X", position="Y"))
        try:
            await session.commit()
        except IntegrityError as exc:
            assert _pg.is_foreign_key_violation(exc)
            assert not _pg.is_unique_violation(exc)
        else:
            raise AssertionError("expected IntegrityError")
