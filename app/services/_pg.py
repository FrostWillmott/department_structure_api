from sqlalchemy.exc import IntegrityError

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def constraint_sqlstate(exc: IntegrityError) -> str | None:
    """Extract the PostgreSQL SQLSTATE code from an asyncpg IntegrityError.

    asyncpg's own exception (with `.sqlstate`) is chained as `exc.orig.__cause__`;
    the DBAPI wrapper (`exc.orig`) also exposes `.sqlstate` directly, used here
    as a fallback in case the chaining ever changes.
    """
    cause = exc.orig.__cause__ if exc.orig is not None else None
    sqlstate = getattr(cause, "sqlstate", None)
    if sqlstate is None and exc.orig is not None:
        sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate if isinstance(sqlstate, str) else None


def is_unique_violation(exc: IntegrityError) -> bool:
    return constraint_sqlstate(exc) == UNIQUE_VIOLATION


def is_foreign_key_violation(exc: IntegrityError) -> bool:
    return constraint_sqlstate(exc) == FOREIGN_KEY_VIOLATION
