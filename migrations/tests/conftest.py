from __future__ import annotations

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from .helpers import (
    ALL_GROUP_ROLES,
    MIGRATIONS_DIR,
    POSTGRES_IMAGE,
    PgReadyWaitStrategy,
)

# Validate constants at import time (catches issues early)
assert len(ALL_GROUP_ROLES) == len(set(ALL_GROUP_ROLES)), (
    "ALL_GROUP_ROLES has duplicates"
)
assert all(ALL_GROUP_ROLES), "ALL_GROUP_ROLES contains empty names"


EXPECTED_UP_FILES = {
    "01_roles.sql",
    "02_reference.sql",
    "03_app.sql",
    "04_audit.sql",
    "05_functions.sql",
    "06_rls.sql",
    "07_audit_triggers.sql",
}

EXPECTED_DOWN_FILES = {
    "01_roles_down.sql",
    "02_reference_down.sql",
    "03_app_down.sql",
    "04_audit_down.sql",
    "05_functions_down.sql",
    "06_rls_down.sql",
    "07_audit_triggers_down.sql",
}


def pytest_configure(config: pytest.Config) -> None:
    for marker, desc in [
        ("reference", "Tests touching reference schema"),
        ("app", "Tests touching app schema"),
        ("audit", "Tests touching audit schema"),
        ("schema", "Schema and object presence tests"),
        ("roles", "Database role behavior tests"),
        ("seed_data", "Reference seed data tests"),
        ("indexes", "Index existence/type tests"),
        ("constraints", "Check/unique constraint tests"),
        ("foreign_keys", "Foreign key behavior tests"),
        ("audit_immutability", "Audit immutability trigger tests"),
        ("privileges", "Privilege grant/denial tests"),
        ("idempotency", "Migration idempotency tests"),
        ("partitioning", "Partition routing tests"),
        ("down_migrations", "Down migration tests"),
        ("rls", "Row level security tests"),
    ]:
        config.addinivalue_line("markers", f"{marker}: {desc}")


@pytest.fixture(scope="session")
def migrated_db():
    """Session-scoped PostgreSQL container with all migrations applied."""
    with _create_postgres_container() as container:
        yield container


@pytest.fixture(scope="session")
def conn_url(migrated_db):
    """Connection URL for the migrated database."""
    return migrated_db.get_connection_url(driver=None)


@pytest.fixture
def superconn(conn_url):
    """Per-test transactional connection with automatic rollback."""
    with psycopg.connect(conn_url, autocommit=False) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="session")
def mutation_db():
    """Session-scoped fresh PostgreSQL container for mutation tests.

    Used by down-migration and idempotency tests that need isolated state
    and apply migrations or schema changes that would mutate shared state.
    """
    with _create_postgres_container() as container:
        yield container


def _create_postgres_container():
    """Create a PostgreSQL container with migrations mounted."""
    return (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(
            str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
        )
        .waiting_for(PgReadyWaitStrategy())
    )
