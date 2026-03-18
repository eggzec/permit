from __future__ import annotations

import pytest
from psycopg import Connection

from app.core.security import get_password_hash
from app.crud.vendor import create_vendor, get_vendor_by_email, get_vendor_by_id


def build_vendor_input(faker) -> tuple[str, str]:
    """
    Builds a vendor email and hashed password pair for CRUD integration tests.

    Used by:
        test_create_vendor_returns_created_row - creates the insert payload for the happy path.
        test_get_vendor_by_email_is_case_insensitive - provisions a vendor before lookup.
        test_create_vendor_returns_none_for_case_insensitive_duplicate - creates the original record used to trigger the duplicate path.
        test_deleted_vendor_is_excluded_from_email_and_id_lookups - provisions the vendor that is later soft-deleted.

    Args:
        faker: `Faker` session fixture used to generate a unique email and password.

    Returns:
        tuple[str, str]: A unique vendor email and its hashed password string.
    """
    return faker.email(), get_password_hash(
        faker.password(length=16, special_chars=True)
    )


@pytest.mark.integration
def test_create_vendor_returns_created_row(db_conn: Connection, faker) -> None:
    """
    Purpose:
        Verifies that `app.crud.vendor.create_vendor` inserts a vendor row and returns the created record.
        This matters because higher-level auth flows depend on CRUD creation returning the persisted vendor identity and email.

    Covers:
        - `app.crud.vendor.create_vendor`

    Rationale:
        This is a real database integration test because vendor creation is fundamentally a persistence contract.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        faker: Session-scoped `Faker` instance used to generate vendor credentials.
    """
    email, password_hash = build_vendor_input(faker)
    with db_conn.cursor() as db_cursor:
        vendor = create_vendor(db_cursor, email, password_hash)

    assert vendor is not None, (
        "Expected create_vendor to return the inserted row"
    )
    assert vendor["email"] == email, (
        f"Expected created vendor email '{email}', got '{vendor['email']}'"
    )
    assert vendor["id"], "Expected create_vendor to return a vendor id"


@pytest.mark.integration
def test_get_vendor_by_email_is_case_insensitive(
    db_conn: Connection, faker
) -> None:
    """
    Purpose:
        Verifies that `app.crud.vendor.get_vendor_by_email` performs case-insensitive email lookup.
        This matters because the auth layer should treat vendor emails consistently regardless of request casing.

    Covers:
        - `app.crud.vendor.create_vendor`
        - `app.crud.vendor.get_vendor_by_email`

    Rationale:
        The test inserts a real row and queries with `upper()` casing so the lookup behavior is proven against PostgreSQL rather than mocked normalization logic.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        faker: Session-scoped `Faker` instance used to generate vendor credentials.
    """
    email, password_hash = build_vendor_input(faker)
    with db_conn.cursor() as db_cursor:
        create_vendor(db_cursor, email, password_hash)
        found_vendor = get_vendor_by_email(db_cursor, email.upper())

    assert found_vendor is not None, (
        f"Expected lookup by '{email.upper()}' to find vendor '{email}'"
    )
    assert found_vendor["email"] == email, (
        f"Expected case-insensitive lookup to return '{email}', got '{found_vendor['email']}'"
    )


@pytest.mark.integration
def test_create_vendor_returns_none_for_case_insensitive_duplicate(
    db_conn: Connection, faker
) -> None:
    """
    Purpose:
        Verifies that `app.crud.vendor.create_vendor` returns `None` when a case-insensitive duplicate email already exists.
        This matters because duplicate vendor emails must be rejected consistently even when the casing differs.

    Covers:
        - `app.crud.vendor.create_vendor`

    Rationale:
        This integration test exercises the duplicate path against the real database because the uniqueness behavior is a persistence concern.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        faker: Session-scoped `Faker` instance used to generate vendor credentials.
    """
    email, password_hash = build_vendor_input(faker)
    with db_conn.cursor() as db_cursor:
        create_vendor(db_cursor, email, password_hash)
        duplicate_vendor = create_vendor(
            db_cursor,
            email.swapcase(),
            get_password_hash(faker.password(length=16, special_chars=True)),
        )

    assert duplicate_vendor is None, (
        "Expected create_vendor to return None when a case-insensitive duplicate email exists"
    )


@pytest.mark.integration
def test_deleted_vendor_is_excluded_from_email_and_id_lookups(
    db_conn: Connection, faker
) -> None:
    """
    Purpose:
        Verifies that `app.crud.vendor.get_vendor_by_email` and `app.crud.vendor.get_vendor_by_id` ignore soft-deleted vendor rows.
        This matters because deleted vendors must not remain visible to auth and business-logic lookups.

    Covers:
        - `app.crud.vendor.create_vendor`
        - `app.crud.vendor.get_vendor_by_email`
        - `app.crud.vendor.get_vendor_by_id`

    Rationale:
        The test marks the persisted row as deleted in SQL and then exercises both lookup paths against the real database state.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        faker: Session-scoped `Faker` instance used to generate vendor credentials.
    """
    email, password_hash = build_vendor_input(faker)
    with db_conn.cursor() as db_cursor:
        vendor = create_vendor(db_cursor, email, password_hash)
        db_cursor.execute(
            'UPDATE app."vendors" SET "deleted_at" = NOW() WHERE "id" = %s',
            (vendor["id"],),
        )
        found_by_email = get_vendor_by_email(db_cursor, email)
        found_by_id = get_vendor_by_id(db_cursor, vendor["id"])

    assert found_by_email is None, (
        "Expected soft-deleted vendor to be excluded from email lookups"
    )
    assert found_by_id is None, (
        "Expected soft-deleted vendor to be excluded from id lookups"
    )
