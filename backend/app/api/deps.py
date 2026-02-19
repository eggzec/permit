from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from psycopg import Cursor


def get_db() -> Generator[Cursor, None, None]:
    """should return the cursor for using with the database"""
    raise NotImplementedError("get_db is not implemented yet")


CursorDep = Annotated[Cursor, Depends(get_db)]
