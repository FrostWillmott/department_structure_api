from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Department(Base):
    """ORM model for a department node in the organizational tree."""

    __tablename__ = "departments"
    # Partial unique indexes: NULL != NULL in PostgreSQL, so a plain UNIQUE on
    # (name, parent_id) would not deduplicate root departments.
    __table_args__ = (
        Index(
            "uq_departments_name_parent",
            "name",
            "parent_id",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
        Index(
            "uq_departments_name_root",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    employees: Mapped[list["Employee"]] = relationship(
        "Employee",
        back_populates="department",
        foreign_keys="Employee.department_id",
        passive_deletes=True,
    )
    children: Mapped[list["Department"]] = relationship(
        "Department",
        foreign_keys="Department.parent_id",
        passive_deletes=True,
    )


class Employee(Base):
    """ORM model for an employee belonging to a department."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str] = mapped_column(String(200), nullable=False)
    hired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    department: Mapped["Department"] = relationship(
        "Department",
        back_populates="employees",
        foreign_keys=[department_id],
    )
