from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from psycopg import Cursor

from app.core.exceptions import APIException
from app.schemas.response import ErrorCode


def get_db(request: Request) -> Generator[Cursor, None, None]:
    """Return a database cursor for the request."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise APIException(
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            message="Database pool not initialized",
            http_status=500,
        )
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            yield cursor


CursorDep = Annotated[Cursor, Depends(get_db)]
