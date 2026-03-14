from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool
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
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(
            str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
        )
        .waiting_for(PgReadyWaitStrategy())
    ) as container:
        with ConnectionPool(
            container.get_connection_url(),
            min_size=4,  # Connections ready at startup
            max_size=20,  # Maximum connections allowed
            open=True,  # Open pool immediately
            check=ConnectionPool.check_connection,  # Test each connection before use
        ) as pool:
            yield pool


@pytest.fixture
def superconn(migrated_db):
    """Per-test transactional connection with automatic rollback, drawn from the pool."""
    with migrated_db.connection() as conn:
        with conn.transaction(force_rollback=True):
            yield conn
