"""
Root conftest - shared fixtures for unit and integration tests.

Key fixtures:
    override_get_db: Module-scoped override of the get_db dependency.
        Starts a dedicated Testcontainers Postgres per module with
        migrations auto-applied via volume mapping.
    db_session: Per-test psycopg cursor inside a transaction that is
        rolled back after each test (full isolation).
"""

from __future__ import annotations

import os
import pathlib
import typing

import pytest
from psycopg import Cursor, connect
from testcontainers.postgres import PostgresContainer

# Set required env vars before importing app so Settings() can instantiate.
# These are dummy values — the real DB connection comes from Testcontainers
# via the get_db dependency override.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PROJECT_NAME", "permit-test")
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")

from app.main import app  # noqa: E402
from app.api.deps import get_db  # noqa: E402

MIGRATIONS_DIR = str(
    pathlib.Path(__file__).resolve().parent.parent.parent / "migrations"
)


# ---------------------------------------------------------------------------
# 1. Override get_db dependency (module-scoped, each module gets its own container)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def override_get_db():
    """Start a dedicated Testcontainers Postgres for this module and
    override the get_db dependency so endpoints receive a cursor from it.

    Each test module gets its own isolated container, avoiding
    cross-module side effects when tests run in parallel.
    """
    with PostgresContainer("postgres:18.2-alpine3.23").with_volume_mapping(
        MIGRATIONS_DIR, "/docker-entrypoint-initdb.d"
    ) as container:
        dsn = container.get_connection_url(driver=None)

        def _get_db() -> typing.Generator[Cursor, None, None]:
            with connect(dsn) as conn:
                with conn.cursor() as cursor:
                    yield cursor

        app.dependency_overrides[get_db] = _get_db
        yield container
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 2. Per-test db_session with transactional rollback
# ---------------------------------------------------------------------------
@pytest.fixture
def db_session(
    override_get_db: PostgresContainer,
) -> typing.Generator[Cursor, None, None]:
    """Provide a psycopg cursor inside an explicit transaction that is
    always rolled back after each test, ensuring full isolation."""
    dsn = override_get_db.get_connection_url(driver=None)
    with connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                yield cursor
            finally:
                cursor.execute("ROLLBACK")
