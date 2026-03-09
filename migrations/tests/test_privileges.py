from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import sql

from .helpers import ALL_GROUP_ROLES, insert_vendor

pytestmark = [
    pytest.mark.privileges,
    pytest.mark.reference,
    pytest.mark.app,
    pytest.mark.audit,
]


@pytest.mark.parametrize(
    "role,sql_stmt,params",
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
    "role,sql_stmt,params",
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
def test_privilege_denial(conn_url, role, sql_stmt, params):
    if role not in ALL_GROUP_ROLES:
        raise ValueError(f"Invalid role: {role}")

    with psycopg.connect(conn_url, autocommit=False) as conn:
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            if role.startswith("app_"):
                conn.execute("SELECT app.set_app_context(%s)", (uuid.uuid4(),))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql_stmt, params)


def test_public_role_has_no_create_on_public_schema(conn_url):
    with psycopg.connect(conn_url) as conn:
        has_create = conn.execute(
            "SELECT has_schema_privilege('public', 'public', 'CREATE')"
        ).fetchone()[0]
    assert not has_create, "PUBLIC should not have CREATE on public schema"


@pytest.mark.parametrize(
    "role,fn_call",
    [
        pytest.param(
            "app_writer",
            "SELECT audit.log_login_success(%s)",
            id="writer_no_audit_schema_usage",
        ),
        pytest.param(
            "app_deleter",
            "SELECT audit.log_login_success(%s)",
            id="deleter_no_audit_schema_usage",
        ),
    ],
)
def test_explicit_audit_functions_blocked_without_audit_schema_usage(
    conn_url, role, fn_call
):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        vendor_id = uuid.uuid4()
        conn.execute("SELECT app.set_app_context(%s)", (vendor_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(fn_call, (vendor_id,))
        conn.rollback()


def test_audit_reader_cannot_execute_insert_log(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE audit_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "SELECT audit._insert_log(%s, uuidv7(), NULL, NULL, NULL, NULL)",
                ("CREATED",),
            )
        conn.rollback()
