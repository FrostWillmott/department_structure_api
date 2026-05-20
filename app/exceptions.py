class DepartmentNotFoundError(Exception):
    """Raised when a department with the given ID does not exist."""

    def __init__(self, dept_id: int) -> None:
        self.dept_id = dept_id
        super().__init__(f"Department {dept_id} not found")


class DuplicateDepartmentNameError(Exception):
    """Raised when a department name is already taken within the same parent."""

    def __init__(self, name: str, parent_id: int | None) -> None:
        self.name = name
        self.parent_id = parent_id
        super().__init__(f"Department '{name}' already exists in this parent")


class CycleDetectedError(Exception):
    """Raised when reparenting a department would create a cycle in the tree."""

    def __init__(self) -> None:
        super().__init__("Moving this department would create a cycle in the tree")


class SelfParentReferenceError(Exception):
    """Raised when a department is set as its own parent."""

    def __init__(self) -> None:
        super().__init__("A department cannot be its own parent")


class InvalidDeleteModeError(Exception):
    """Raised when mode=reassign is used without reassign_to_department_id."""

    def __init__(self) -> None:
        super().__init__("reassign_to_department_id is required when mode=reassign")


class ReassignTargetNotFoundError(Exception):
    """Raised when the reassign target department does not exist."""

    def __init__(self, dept_id: int) -> None:
        self.dept_id = dept_id
        super().__init__(f"Reassign target department {dept_id} not found")
