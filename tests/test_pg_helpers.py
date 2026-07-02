from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import Employee
from app.services import _pg


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
