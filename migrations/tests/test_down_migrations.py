from __future__ import annotations

import pytest

from .helpers import (
    ALL_GROUP_ROLES,
    DOWN_MIGRATIONS,
    MIGRATIONS_DIR,
    UP_MIGRATIONS,
    apply_sql_file,
    snapshot_db_state,
)


@pytest.fixture
def db_after_down_migrations(superconn):
    """Apply all DOWN_MIGRATIONS in-transaction and return the same connection."""
    with superconn.cursor() as cur:
        for filename in DOWN_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)
    return superconn


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_remove_schemas(db_after_down_migrations):
    expected_schemas = ["reference", "app", "audit"]
    schemas = db_after_down_migrations.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
        (expected_schemas,),
    ).fetchall()
    assert len(schemas) == 0, (
        f"Expected schemas {expected_schemas} to be removed, found {schemas}"
    )


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_remove_all_roles(db_after_down_migrations):
    roles = db_after_down_migrations.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
        (ALL_GROUP_ROLES,),
    ).fetchall()
    assert len(roles) == 0, f"Expected all managed roles to be removed, found {roles}"


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_remove_trigger_function(db_after_down_migrations):
    schema_name = "audit"
    function_name = "prevent_audit_update_delete"
    row = db_after_down_migrations.execute(
        "SELECT proname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname=%s AND p.proname=%s",
        (schema_name, function_name),
    ).fetchone()
    assert row is None, (
        f"Expected {schema_name}.{function_name} to be removed, found {row}"
    )


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_restore_public_schema_privileges(db_after_down_migrations):
    create_ok = False
    usage_ok = False
    try:
        db_after_down_migrations.execute("CREATE ROLE pub_test LOGIN PASSWORD 'x'")
        create_ok = db_after_down_migrations.execute(
            "SELECT has_schema_privilege('pub_test','public','CREATE')"
        ).fetchone()[0]
        usage_ok = db_after_down_migrations.execute(
            "SELECT has_schema_privilege('pub_test','public','USAGE')"
        ).fetchone()[0]
    finally:
        db_after_down_migrations.execute("DROP ROLE IF EXISTS pub_test")

    assert create_ok is True, "PUBLIC CREATE on public schema not restored"
    assert usage_ok is True, "PUBLIC USAGE on public schema not restored"


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_are_idempotent(superconn):
    with superconn.cursor() as cur:
        for filename in DOWN_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)
        for filename in DOWN_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)


@pytest.mark.down_migrations
@pytest.mark.audit
def test_trigger_down_resilient_to_missing_relation(superconn):
    """A4: DROP TRIGGER IF EXISTS ... ON relation still fails when the relation itself is absent.

    This test FAILS before the fix in 07_audit_triggers_down.sql because
    DROP TRIGGER IF EXISTS suppresses the missing-trigger error but NOT a missing-relation error.
    After wrapping each DROP TRIGGER in a DO block that guards with a relation existence check,
    this test passes.
    """
    # Drop the view that the down migration references for DROP TRIGGER
    superconn.execute("DROP VIEW IF EXISTS app.v_license_node_locked CASCADE")

    # Applying the down migration MUST NOT fail even though the view is gone
    with superconn.cursor() as cur:
        apply_sql_file(cur, MIGRATIONS_DIR / "down/07_audit_triggers_down.sql")


@pytest.mark.down_migrations
@pytest.mark.audit
def test_revoke_down_resilient_to_missing_role(superconn):
    """A11: REVOKE ... FROM role fails when the role no longer exists.

    This test FAILS before the fix in 05_functions_down.sql because the REVOKE statements
    guard for function existence but not for role existence. After wrapping each REVOKE
    in a DO block that checks both function AND role existence, this test passes.
    """
    # Drop app_writer (strip its owned objects first so DROP ROLE succeeds)
    superconn.execute("DROP OWNED BY app_writer; DROP ROLE app_writer")

    with superconn.cursor() as cur:
        # Prerequisites for 05_functions_down.sql
        apply_sql_file(cur, MIGRATIONS_DIR / "down/07_audit_triggers_down.sql")
        apply_sql_file(cur, MIGRATIONS_DIR / "down/06_rls_down.sql")

        # This MUST NOT fail even though app_writer no longer exists
        apply_sql_file(cur, MIGRATIONS_DIR / "down/05_functions_down.sql")


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_up_after_down_restores_full_state(superconn):
    reference_snapshot = snapshot_db_state(superconn)

    with superconn.cursor() as cur:
        for filename in DOWN_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)
        for filename in UP_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)

    restored_snapshot = snapshot_db_state(superconn)
    assert restored_snapshot == reference_snapshot, (
        "DB state after down+up does not match a fresh migration"
    )
