from __future__ import annotations

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from .helpers import (
    ALL_GROUP_ROLES,
    DOWN_MIGRATIONS,
    MIGRATIONS_DIR,
    POSTGRES_IMAGE,
    UP_MIGRATIONS,
    PgReadyWaitStrategy,
    apply_sql_file,
    snapshot_db_state,
)


@pytest.fixture
def db_after_down_migrations(mutation_db):
    """Apply all DOWN_MIGRATIONS to the database and return it."""
    for filename in DOWN_MIGRATIONS:
        apply_sql_file(mutation_db, MIGRATIONS_DIR / filename)
    return mutation_db


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_remove_schemas(db_after_down_migrations):
    url = db_after_down_migrations.get_connection_url(driver=None)
    expected_schemas = ["reference", "app", "audit"]
    with psycopg.connect(url) as conn:
        schemas = conn.execute(
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
    url = db_after_down_migrations.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        roles = conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
            (ALL_GROUP_ROLES,),
        ).fetchall()
    assert len(roles) == 0, f"Expected all managed roles to be removed, found {roles}"


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_remove_trigger_function(db_after_down_migrations):
    url = db_after_down_migrations.get_connection_url(driver=None)
    schema_name = "audit"
    function_name = "prevent_audit_update_delete"
    with psycopg.connect(url) as conn:
        row = conn.execute(
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
    url = db_after_down_migrations.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        create_ok = False
        usage_ok = False
        try:
            conn.execute("CREATE ROLE pub_test LOGIN PASSWORD 'x'")
            conn.commit()
            create_ok = conn.execute(
                "SELECT has_schema_privilege('pub_test','public','CREATE')"
            ).fetchone()[0]
            usage_ok = conn.execute(
                "SELECT has_schema_privilege('pub_test','public','USAGE')"
            ).fetchone()[0]
        finally:
            conn.execute("DROP ROLE IF EXISTS pub_test")
            conn.commit()

        assert create_ok is True, "PUBLIC CREATE on public schema not restored"
        assert usage_ok is True, "PUBLIC USAGE on public schema not restored"


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_are_idempotent(mutation_db):
    for filename in DOWN_MIGRATIONS:
        apply_sql_file(mutation_db, MIGRATIONS_DIR / filename)
    for filename in DOWN_MIGRATIONS:
        apply_sql_file(mutation_db, MIGRATIONS_DIR / filename)


@pytest.mark.down_migrations
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_up_after_down_restores_full_state(mutation_db):
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(
            str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
        )
        .waiting_for(PgReadyWaitStrategy()) as reference_container
    ):
        reference_snapshot = snapshot_db_state(reference_container)

    for filename in DOWN_MIGRATIONS:
        apply_sql_file(mutation_db, MIGRATIONS_DIR / filename)
    for filename in UP_MIGRATIONS:
        apply_sql_file(mutation_db, MIGRATIONS_DIR / filename)

    restored_snapshot = snapshot_db_state(mutation_db)
    assert restored_snapshot == reference_snapshot, (
        "DB state after down+up does not match a fresh migration"
    )
