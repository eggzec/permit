from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from psycopg import Cursor


def get_db(request: Request) -> Generator[Cursor, None, None]:
    """Return a database cursor for the request."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            yield cursor


CursorDep = Annotated[Cursor, Depends(get_db)]
