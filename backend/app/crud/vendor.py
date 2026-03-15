"""CRUD operations for the vendors table (raw psycopg)."""

from __future__ import annotations

from typing import Any

from psycopg import Cursor


def get_vendor_by_email(cursor: Cursor, email: str) -> dict[str, Any] | None:
    """Return a vendor row by email (case-insensitive) or None.

    Returns:
        dict[str, Any] | None: The vendor row or None.
    """
    cursor.execute(  # SQL
        """
        SELECT "id", "email", "password_hash"
        FROM app."vendors"
        WHERE LOWER("email") = LOWER(%s)
        AND "deleted_at" IS NULL
        """,
        (email,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1], "password_hash": row[2]}


def get_vendor_by_id(cursor: Cursor, vendor_id: str) -> dict[str, Any] | None:
    """Return a vendor row by id or None.

    Returns:
        dict[str, Any] | None: The vendor row or None.
    """
    cursor.execute(  # SQL
        """
        SELECT "id", "email"
        FROM app."vendors"
        WHERE "id" = %s AND "deleted_at" IS NULL
        """,
        (vendor_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1]}


def create_vendor(
    cursor: Cursor, email: str, password_hash: str
) -> dict[str, Any] | None:
    """Insert a new vendor and return the created row.

    Uses ON CONFLICT DO NOTHING so a concurrent insert with the same
    (case-insensitive) email returns None instead of raising a
    UniqueViolation.

    Returns:
        dict[str, Any] | None: The created vendor row, or None on conflict.
    """
    cursor.execute(  # SQL
        """
        INSERT INTO app."vendors" ("email", "password_hash")
        VALUES (%s, %s)
        ON CONFLICT (LOWER("email")) DO NOTHING
        RETURNING "id", "email"
        """,
        (email, password_hash),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1]}
