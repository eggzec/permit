from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import sql

from .helpers import ALL_GROUP_ROLES, insert_license, insert_session, insert_vendor

pytestmark = [
    pytest.mark.privileges,
    pytest.mark.reference,
    pytest.mark.app,
    pytest.mark.audit,
]


@pytest.mark.parametrize(
    ("role", "sql_stmt", "params"),
    [
        pytest.param(
            "app_reader_rls",
            'SELECT COUNT(*) FROM app."vendors"',
            (),
            id="reader_select",
        ),
        pytest.param(
            "reference_writer",
            'INSERT INTO reference."actions" (code, description) VALUES (%s,%s)',
            ("TEST_ACTION", "Test action for writer privilege check"),
            id="writer_insert",
        ),
        pytest.param(
            "reference_reader",
            'SELECT COUNT(*) FROM reference."license_statuses"',
            (),
            id="reference_reader_select",
        ),
        pytest.param(
            "audit_writer",
            'INSERT INTO audit."audit_logs" (action_code) VALUES (%s)',
            ("CREATED",),
            id="audit_writer_insert",
        ),
        pytest.param(
            "audit_reader",
            'SELECT COUNT(*) FROM audit."audit_logs"',
            (),
            id="audit_reader_select",
        ),
    ],
)
def test_privilege_grant_simple(superconn, role, sql_stmt, params):
    if role not in ALL_GROUP_ROLES:
        raise ValueError(f"Invalid role: {role}")

    with superconn.transaction(force_rollback=True):
        superconn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        if role.startswith("app_"):
            superconn.execute("SELECT app.set_app_context(%s)", (uuid.uuid4(),))
        superconn.execute(sql_stmt, params)


def test_app_writer_can_update(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "writer-upd@example.com")
        superconn.execute("SET LOCAL ROLE app_writer")
        superconn.execute("SELECT app.set_app_context(%s)", (vid,))
        superconn.execute(
            'UPDATE app."vendors" SET updated_at=NOW() WHERE id=%s', (vid,)
        )


def test_app_deleter_can_delete(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "deleter-ok@example.com")
        superconn.execute("SET LOCAL ROLE app_deleter")
        superconn.execute("SELECT app.set_app_context(%s)", (vid,))
        superconn.execute('DELETE FROM app."vendors" WHERE id=%s', (vid,))


@pytest.mark.parametrize(
    ("role", "sql_stmt", "params"),
    [
        pytest.param(
            "app_reader_rls",
            'INSERT INTO app."vendors" (email, password_hash) VALUES (%s,%s)',
            ("reader-fail@example.com", "hash"),
            id="reader_no_insert",
        ),
        pytest.param(
            "app_reader_rls",
            'UPDATE app."vendors" SET updated_at=NOW()',
            (),
            id="reader_no_update",
        ),
        pytest.param(
            "app_reader_rls", 'DELETE FROM app."vendors"', (), id="reader_no_delete"
        ),
        pytest.param(
            "app_writer", 'DELETE FROM app."vendors"', (), id="writer_no_delete"
        ),
        pytest.param(
            "app_deleter",
            'INSERT INTO app."vendors" (email, password_hash) VALUES (%s,%s)',
            ("deleter-insert-fail@example.com", "hash"),
            id="deleter_no_insert",
        ),
        pytest.param(
            "app_deleter",
            'UPDATE app."vendors" SET updated_at=NOW()',
            (),
            id="deleter_no_update",
        ),
        pytest.param(
            "reference_reader",
            'INSERT INTO reference."license_statuses" (code, description) VALUES (%s,%s)',
            ("FAKE", "should fail"),
            id="reference_reader_no_insert",
        ),
        pytest.param(
            "reference_writer",
            'UPDATE reference."license_statuses" SET description=%s WHERE code=%s',
            ("hacked", "ACTIVE"),
            id="reference_writer_no_update",
        ),
        pytest.param(
            "reference_writer",
            'DELETE FROM reference."license_statuses"',
            (),
            id="reference_writer_no_delete",
        ),
        pytest.param(
            "audit_writer",
            'SELECT COUNT(*) FROM audit."audit_logs"',
            (),
            id="audit_writer_no_select",
        ),
        pytest.param(
            "audit_reader",
            'INSERT INTO audit."audit_logs" (action_code) VALUES (%s)',
            ("CREATED",),
            id="audit_reader_no_insert",
        ),
        pytest.param(
            "app_reader_rls",
            'SELECT * FROM reference."license_statuses"',
            (),
            id="reader_no_reference_access",
        ),
    ],
)
def test_privilege_denial(superconn, role, sql_stmt, params):
    if role not in ALL_GROUP_ROLES:
        raise ValueError(f"Invalid role: {role}")

    with superconn.transaction(force_rollback=True):
        superconn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        if role.startswith("app_"):
            superconn.execute("SELECT app.set_app_context(%s)", (uuid.uuid4(),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute(sql_stmt, params)


def test_public_role_has_no_create_on_public_schema(superconn):
    has_create = superconn.execute(
        "SELECT has_schema_privilege('public', 'public', 'CREATE')"
    ).fetchone()[0]
    assert not has_create, "PUBLIC should not have CREATE on public schema"


def test_audit_reader_select_through_licenses_rls_delegation(superconn):
    """FAILS before A2 fix: audit_reader lacks SELECT on app.licenses required by the
    audit_log_licenses_select_own RLS policy which delegates via EXISTS(SELECT ... FROM app.licenses).
    After fix (GRANT SELECT on app.licenses TO audit_reader) this test passes.
    """
    with superconn.transaction(force_rollback=True):
        vendor_id = insert_vendor(superconn, "audit-del-licenses@example.com")
        license_id = insert_license(superconn, vendor_id)

        # Set up audit data as audit_owner (must set role before inserting into audit tables)
        superconn.execute("SET LOCAL ROLE audit_owner")
        log_id = superconn.execute(
            'INSERT INTO audit."audit_logs" (action_code) VALUES (%s) RETURNING id',
            ("CREATED",),
        ).fetchone()[0]
        superconn.execute(
            'INSERT INTO audit."audit_log_licenses" (audit_log_id, license_id) VALUES (%s,%s)',
            (log_id, license_id),
        )

        # As audit_reader with app context: the RLS policy on audit_log_licenses delegates
        # through app.licenses. Without SELECT on app.licenses this raises InsufficientPrivilege.
        superconn.execute("SET LOCAL ROLE audit_reader")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_id,))
        rows = superconn.execute(
            'SELECT license_id FROM audit."audit_log_licenses" WHERE audit_log_id=%s',
            (log_id,),
        ).fetchall()
        assert len(rows) > 0, (
            "audit_reader should see audit_log_licenses rows via delegated RLS"
        )


def test_audit_reader_select_through_sessions_rls_delegation(superconn):
    """FAILS before A2 fix: audit_reader lacks SELECT on app.sessions required by the
    audit_log_sessions_select_own RLS policy which delegates via EXISTS(SELECT ... FROM app.sessions).
    After fix (GRANT SELECT on app.sessions TO audit_reader) this test passes.
    """
    with superconn.transaction(force_rollback=True):
        vendor_id = insert_vendor(superconn, "audit-del-sessions@example.com")
        license_id = insert_license(superconn, vendor_id)
        session_id = insert_session(superconn, license_id)

        # Set up audit data as audit_owner (must set role before inserting into audit tables)
        superconn.execute("SET LOCAL ROLE audit_owner")
        log_id = superconn.execute(
            'INSERT INTO audit."audit_logs" (action_code) VALUES (%s) RETURNING id',
            ("CREATED",),
        ).fetchone()[0]
        superconn.execute(
            'INSERT INTO audit."audit_log_sessions" (audit_log_id, session_id) VALUES (%s,%s)',
            (log_id, session_id),
        )

        # As audit_reader with app context: the RLS policy on audit_log_sessions delegates
        # through app.sessions. Without SELECT on app.sessions this raises InsufficientPrivilege.
        superconn.execute("SET LOCAL ROLE audit_reader")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_id,))
        rows = superconn.execute(
            'SELECT session_id FROM audit."audit_log_sessions" WHERE audit_log_id=%s',
            (log_id,),
        ).fetchall()
        assert len(rows) > 0, (
            "audit_reader should see audit_log_sessions rows via delegated RLS"
        )


def test_audit_reader_cannot_execute_insert_log(superconn):
    with superconn.transaction(force_rollback=True):
        superconn.execute("SET LOCAL ROLE audit_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute(
                "SELECT audit._insert_log(%s, uuidv7(), NULL, NULL, NULL, NULL)",
                ("CREATED",),
            )


def test_app_writer_can_invoke_audit_log_via_view_write(superconn):
    """Regression guard: 01_roles.sql grants USAGE ON SCHEMA audit to app_writer/
    app_deleter so the SECURITY INVOKER trigger on v_license_node_locked can call
    audit functions. This test confirms that grant is present and functional.
    """
    with superconn.transaction(force_rollback=True):
        vendor_id = insert_vendor(superconn, "app-writer-audit-call@example.com")
        insert_license(superconn, vendor_id)
        superconn.execute("SET LOCAL ROLE app_writer")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_id,))
        # Calling the audit write function directly confirms USAGE + EXECUTE grants.
        # (The view trigger calls this under the hood on every licence write.)
        superconn.execute("SELECT audit.log_login_success(%s)", (vendor_id,))
