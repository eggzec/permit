from __future__ import annotations

import pytest
from psycopg import sql

pytestmark = [pytest.mark.rls, pytest.mark.app, pytest.mark.audit]


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("licenses", id="licenses"),
        pytest.param("node_locked_license_data", id="node_locked_license_data"),
        pytest.param("sessions", id="sessions"),
        pytest.param("heartbeats", id="heartbeats"),
    ],
)
def test_rls_enabled_on_tenant_table(superconn, table):
    schema_name = "app"
    row = superconn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE relname = %s "
        "AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname=%s)",
        (table, schema_name),
    ).fetchone()
    assert row is not None, f"Table app.{table} not found"
    assert row[0] is True, f"RLS not enabled on app.{table}"


@pytest.mark.parametrize(
    "table,policy",
    [
        pytest.param("licenses", "licenses_select_own", id="licenses_select"),
        pytest.param("licenses", "licenses_insert_own", id="licenses_insert"),
        pytest.param("licenses", "licenses_update_own", id="licenses_update"),
        pytest.param("licenses", "licenses_delete_own", id="licenses_delete"),
        pytest.param(
            "node_locked_license_data",
            "node_locked_select_own",
            id="node_locked_select",
        ),
        pytest.param(
            "node_locked_license_data",
            "node_locked_insert_own",
            id="node_locked_insert",
        ),
        pytest.param(
            "node_locked_license_data",
            "node_locked_update_own",
            id="node_locked_update",
        ),
        pytest.param(
            "node_locked_license_data",
            "node_locked_delete_own",
            id="node_locked_delete",
        ),
        pytest.param("sessions", "sessions_select_own", id="sessions_select"),
        pytest.param("sessions", "sessions_insert_own", id="sessions_insert"),
        pytest.param("sessions", "sessions_update_own", id="sessions_update"),
        pytest.param("sessions", "sessions_delete_own", id="sessions_delete"),
        pytest.param("heartbeats", "heartbeats_select_own", id="heartbeats_select"),
        pytest.param("heartbeats", "heartbeats_insert_own", id="heartbeats_insert"),
        pytest.param("heartbeats", "heartbeats_update_own", id="heartbeats_update"),
        pytest.param("heartbeats", "heartbeats_delete_own", id="heartbeats_delete"),
    ],
)
def test_rls_policy_exists(superconn, table, policy):
    row = superconn.execute(
        "SELECT 1 FROM pg_policies "
        "WHERE tablename = %s AND policyname = %s AND schemaname = %s",
        (table, policy, "app"),
    ).fetchone()
    assert row is not None, f"Policy '{policy}' not found on table app.{table}"


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("audit_logs", id="audit_logs"),
        pytest.param("audit_log_vendor_actors", id="audit_log_vendor_actors"),
        pytest.param("audit_log_licenses", id="audit_log_licenses"),
        pytest.param("audit_log_sessions", id="audit_log_sessions"),
    ],
)
def test_rls_enabled_on_audit_table(superconn, table):
    schema_name = "audit"
    row = superconn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE relname = %s "
        "AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname=%s)",
        (table, schema_name),
    ).fetchone()
    assert row is not None, f"Table audit.{table} not found"
    assert row[0] is True, f"RLS not enabled on audit.{table}"


@pytest.mark.parametrize(
    "table,policy",
    [
        pytest.param("audit_logs", "audit_logs_insert_writer", id="audit_logs_insert"),
        pytest.param(
            "audit_log_vendor_actors",
            "audit_log_vendor_actors_insert_writer",
            id="audit_log_vendor_actors_insert",
        ),
        pytest.param(
            "audit_log_licenses",
            "audit_log_licenses_insert_writer",
            id="audit_log_licenses_insert",
        ),
        pytest.param(
            "audit_log_sessions",
            "audit_log_sessions_insert_writer",
            id="audit_log_sessions_insert",
        ),
        pytest.param("audit_logs", "audit_logs_select_own", id="audit_logs_select"),
        pytest.param(
            "audit_log_vendor_actors",
            "audit_log_vendor_actors_select_own",
            id="audit_log_vendor_actors_select",
        ),
        pytest.param(
            "audit_log_licenses",
            "audit_log_licenses_select_own",
            id="audit_log_licenses_select",
        ),
        pytest.param(
            "audit_log_sessions",
            "audit_log_sessions_select_own",
            id="audit_log_sessions_select",
        ),
    ],
)
def test_audit_rls_policies_exist(superconn, table, policy):
    row = superconn.execute(
        "SELECT 1 FROM pg_policies WHERE schemaname=%s AND tablename=%s AND policyname=%s",
        ("audit", table, policy),
    ).fetchone()
    assert row is not None, (
        f"Audit RLS policy '{policy}' missing on table audit.{table}"
    )


def test_set_app_context_function_exists(superconn):
    schema_name = "app"
    function_name = "set_app_context"
    row = superconn.execute(
        "SELECT 1 FROM pg_proc p "
        "JOIN pg_namespace n ON p.pronamespace = n.oid "
        "WHERE n.nspname = %s AND p.proname = %s",
        (schema_name, function_name),
    ).fetchone()
    assert row is not None, f"{schema_name}.{function_name} function not found"


def test_set_app_context_not_executable_by_public(superconn):
    routine_schema = "app"
    routine_name = "set_app_context"
    grants = [
        r[0]
        for r in superconn.execute(
            "SELECT grantee FROM information_schema.routine_privileges "
            "WHERE routine_schema=%s AND routine_name=%s "
            "ORDER BY grantee",
            (routine_schema, routine_name),
        ).fetchall()
    ]
    assert "PUBLIC" not in grants, "PUBLIC should not have EXECUTE on set_app_context"


def test_set_app_context_owned_by_app_owner(superconn):
    schema_name = "app"
    function_name = "set_app_context"
    row = superconn.execute(
        "SELECT r.rolname "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = %s AND p.proname = %s",
        (schema_name, function_name),
    ).fetchone()
    assert row is not None, "app.set_app_context function not found"
    assert row[0] == "app_owner", (
        f"Expected {schema_name}.{function_name} owner to be app_owner, got {row[0]}"
    )


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("licenses", id="licenses"),
        pytest.param("node_locked_license_data", id="node_locked_license_data"),
        pytest.param("sessions", id="sessions"),
        pytest.param("heartbeats", id="heartbeats"),
    ],
)
def test_rls_tenant_tables_owned_by_app_owner(superconn, table):
    schema_name = "app"
    row = superconn.execute(
        "SELECT r.rolname "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_roles r ON r.oid = c.relowner "
        "WHERE n.nspname = %s AND c.relname = %s",
        (schema_name, table),
    ).fetchone()
    assert row is not None, f"app.{table} not found"
    assert row[0] == "app_owner", (
        f"Expected app.{table} owner to be app_owner, got {row[0]}"
    )


def test_audit_immutability_function_owned_by_audit_owner(superconn):
    schema_name = "audit"
    function_name = "prevent_audit_update_delete"
    row = superconn.execute(
        "SELECT r.rolname "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = %s AND p.proname = %s",
        (schema_name, function_name),
    ).fetchone()
    assert row is not None, "audit.prevent_audit_update_delete function not found"
    assert row[0] == "audit_owner", (
        f"Expected {schema_name}.{function_name} owner to be audit_owner, got {row[0]}"
    )


@pytest.mark.parametrize(
    "function_name,expected_owner",
    [
        pytest.param(
            "_insert_log", "audit_owner", id="insert_log_owned_by_audit_owner"
        ),
        pytest.param(
            "log_login_success",
            "audit_owner",
            id="log_login_success_owned_by_audit_owner",
        ),
        pytest.param(
            "log_login_failed",
            "audit_owner",
            id="log_login_failed_owned_by_audit_owner",
        ),
        pytest.param(
            "log_token_refreshed",
            "audit_owner",
            id="log_token_refreshed_owned_by_audit_owner",
        ),
        pytest.param(
            "log_heartbeat_error",
            "audit_owner",
            id="log_heartbeat_error_owned_by_audit_owner",
        ),
        pytest.param(
            "trg_vendors_audit", "audit_owner", id="trg_vendors_owned_by_audit_owner"
        ),
        pytest.param(
            "trg_sessions_audit", "audit_owner", id="trg_sessions_owned_by_audit_owner"
        ),
        pytest.param(
            "trg_v_license_node_locked_write",
            "audit_owner",
            id="trg_view_write_owned_by_audit_owner",
        ),
        pytest.param(
            "trg_v_license_node_locked_delete",
            "audit_owner",
            id="trg_view_delete_owned_by_audit_owner",
        ),
    ],
)
def test_new_functions_have_expected_owners(superconn, function_name, expected_owner):
    schema_name = "audit"
    row = superconn.execute(
        "SELECT r.rolname "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = %s AND p.proname = %s",
        (schema_name, function_name),
    ).fetchone()
    assert row is not None, f"audit.{function_name} function not found"
    assert row[0] == expected_owner, (
        f"Expected audit.{function_name} owner to be {expected_owner}, got {row[0]}"
    )


def test_trigger_objects_exist(superconn):
    expected = {
        "vendors_audit_tr",
        "sessions_audit_tr",
        "v_license_node_locked_write_tr",
        "v_license_node_locked_delete_tr",
    }
    found = {
        row[0]
        for row in superconn.execute(
            sql.SQL(
                "SELECT tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE NOT t.tgisinternal AND n.nspname=%s AND c.relname IN ({})"
            ).format(sql.SQL(", ").join(sql.Placeholder() * 3)),
            ("app", "vendors", "sessions", "v_license_node_locked"),
        ).fetchall()
    }
    missing = sorted(expected - found)
    assert not missing, f"Missing expected triggers: {missing}"
