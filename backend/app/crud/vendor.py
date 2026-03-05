"""CRUD operations for the vendors table (raw psycopg)."""

from __future__ import annotations

from typing import Any

from psycopg import Cursor


def get_vendor_by_email(cursor: Cursor, email: str) -> dict[str, Any] | None:
    """Return a vendor row by email (case-insensitive) or None."""
    cursor.execute(
        'SELECT "id", "email", "password_hash" '
        'FROM app."vendors" '
        'WHERE LOWER("email") = LOWER(%s) '
        'AND "deleted_at" IS NULL',
        (email,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1], "password_hash": row[2]}


def get_vendor_by_id(cursor: Cursor, vendor_id: str) -> dict[str, Any] | None:
    """Return a vendor row by id or None."""
    cursor.execute(
        'SELECT "id", "email" '
        'FROM app."vendors" '
        'WHERE "id" = %s AND "deleted_at" IS NULL',
        (vendor_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1]}


def create_vendor(cursor: Cursor, email: str, password_hash: str) -> dict[str, Any]:
    """Insert a new vendor and return the created row."""
    cursor.execute(
        'INSERT INTO app."vendors" ("email", "password_hash") '
        "VALUES (%s, %s) "
        'RETURNING "id", "email"',
        (email, password_hash),
    )
    row = cursor.fetchone()
    assert row is not None
    return {"id": str(row[0]), "email": row[1]}
