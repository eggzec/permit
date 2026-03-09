from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from _legacy_test_migrations import (
    ALL_GROUP_ROLES,
    MIGRATIONS_DIR,
    POSTGRES_IMAGE,
    PgReadyWaitStrategy,
)

EXPECTED_TEST_MODULES = {
    "test_schema.py",
    "test_idempotency.py",
    "test_roles.py",
    "test_seed_data.py",
    "test_indexes.py",
    "test_constraints.py",
    "test_partitioning.py",
    "test_audit.py",
    "test_privileges.py",
    "test_down_migrations.py",
    "test_rls_structure.py",
    "test_rls_isolation.py",
}

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


def pytest_sessionstart(session: pytest.Session) -> None:
    tests_dir = Path(__file__).parent
    missing_modules = sorted(
        name for name in EXPECTED_TEST_MODULES if not (tests_dir / name).exists()
    )
    if missing_modules:
        raise pytest.UsageError(
            "Missing expected migration test modules: " + ", ".join(missing_modules)
        )

    missing_up = sorted(name for name in EXPECTED_UP_FILES if not (MIGRATIONS_DIR / name).exists())
    missing_down = sorted(
        name for name in EXPECTED_DOWN_FILES if not (MIGRATIONS_DIR / "down" / name).exists()
    )
    if missing_up or missing_down:
        details = []
        if missing_up:
            details.append("up: " + ", ".join(missing_up))
        if missing_down:
            details.append("down: " + ", ".join(missing_down))
        raise pytest.UsageError("Missing migration files: " + " | ".join(details))

    if len(ALL_GROUP_ROLES) != len(set(ALL_GROUP_ROLES)) or any(not r for r in ALL_GROUP_ROLES):
        raise pytest.UsageError("ALL_GROUP_ROLES must contain unique, non-empty role names")


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    if len(items) < 60:
        raise pytest.UsageError(
            f"Unexpectedly low migration test count ({len(items)}). "
            "Check module wiring in migrations/tests/."
        )


@pytest.fixture(scope="session")
def migrated_db():
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro")
        .waiting_for(PgReadyWaitStrategy()) as container
    ):
        yield container


@pytest.fixture(scope="session")
def conn_url(migrated_db):
    return migrated_db.get_connection_url(driver=None)


@pytest.fixture
def superconn(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def fresh_db():
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro")
        .waiting_for(PgReadyWaitStrategy()) as container
    ):
        yield container
