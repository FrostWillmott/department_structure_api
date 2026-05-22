from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


def _strip_string(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class DepartmentCreate(BaseModel):
    """Request body for creating a new department."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Department name. Must be unique within the same parent.",
    )
    parent_id: int | None = Field(
        None,
        description="Parent department ID. Null creates a root-level department.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        """Strip leading and trailing whitespace."""
        return _strip_string(v)


class DepartmentUpdate(BaseModel):
    """Request body for partially updating a department."""

    name: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        description="New department name.",
    )
    parent_id: int | None = Field(
        None,
        description="New parent department ID. Null moves the department to root.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        """Strip leading and trailing whitespace."""
        return _strip_string(v)

    @model_validator(mode="after")
    def name_not_null_if_provided(self) -> "DepartmentUpdate":
        """Reject explicit name: null — omit the field to leave the name unchanged."""
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError(
                "name cannot be null; omit the field to leave it unchanged"
            )
        return self


class DepartmentBase(BaseModel):
    """Base response schema for a department."""

    model_config = {"from_attributes": True}

    id: int = Field(..., description="Unique department identifier")
    name: str = Field(..., description="Department name")
    parent_id: int | None = Field(None, description="Parent department ID")
    created_at: datetime = Field(..., description="UTC timestamp of creation")


class EmployeeResponse(BaseModel):
    """Response schema for an employee."""

    model_config = {"from_attributes": True}

    id: int = Field(..., description="Unique employee identifier")
    department_id: int = Field(..., description="Department the employee belongs to")
    full_name: str = Field(..., description="Employee full name")
    position: str = Field(..., description="Job position title")
    hired_at: date | None = Field(None, description="Hire date")
    created_at: datetime = Field(..., description="UTC timestamp of creation")


class DepartmentDetail(DepartmentBase):
    """Detailed department response including employees and child departments."""

    employees: list[EmployeeResponse] = Field(
        default_factory=list,
        description="Department employees, sorted by the sort_employees_by parameter.",
    )
    children: list["DepartmentDetail"] = Field(
        default_factory=list,
        description="Child departments, recursively nested up to the requested depth.",
    )


class EmployeeCreate(BaseModel):
    """Request body for creating a new employee."""

    full_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Employee full name",
    )
    position: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Job position title",
    )
    hired_at: date | None = Field(None, description="Hire date")

    @field_validator("full_name", "position", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        """Strip leading and trailing whitespace."""
        return _strip_string(v)
