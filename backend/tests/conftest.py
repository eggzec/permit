"""
Root conftest - shared fixtures for unit and integration tests.

Key fixtures:
    postgres_container: Session-scoped Testcontainers PostgreSQL instance.
    app: FastAPI application wired to the test database.
    client: httpx.AsyncClient bound to the app.
    db_session: Per-test psycopg cursor inside a transaction that is
        rolled back after each test (full isolation).
"""

from __future__ import annotations

import typing
from psycopg import Cursor

import logging
import os
from collections.abc import Generator


import psycopg
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient


from testcontainers.postgres import PostgresContainer
from psycopg import connect

# Load .env before importing app.main to ensure env vars are set
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path)

# noqa: E402 to allow imports after env setup
from app.main import app  # noqa: E402
from app.api.deps import get_db  # noqa: E402

logger = logging.getLogger(__name__)


def _make_dsn(container: PostgresContainer) -> str:
    dsn = container.get_connection_url()
    # Patch SQLAlchemy/Testcontainers DSN to psycopg3-compatible
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = dsn.replace("postgresql+psycopg2://", "postgresql://", 1)
    return dsn


# ---------------------------------------------------------------------------
# 1. Testcontainers - session-scoped Postgres
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start a PostgreSQL container once for the entire test session.

    The container is stopped automatically when the session ends.

    Yields:
        A running PostgresContainer instance.
    """
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


# ---------------------------------------------------------------------------
# 2. Environment variables for the test session
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _set_test_env(postgres_container: PostgresContainer) -> None:
    """Override environment variables for the test session.

    Sets connection details so that ``app.core.config.Settings`` picks up
    the Testcontainers Postgres instance instead of a real database.

    Args:
        postgres_container: The running Testcontainers Postgres instance.
    """
    os.environ["POSTGRES_SERVER"] = postgres_container.get_container_host_ip()
    os.environ["POSTGRES_PORT"] = str(postgres_container.get_exposed_port(5432))
    os.environ["POSTGRES_USER"] = postgres_container.username
    os.environ["POSTGRES_PASSWORD"] = postgres_container.password
    os.environ["POSTGRES_DB"] = postgres_container.dbname
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
    os.environ["PROJECT_NAME"] = "permit-test"


# ---------------------------------------------------------------------------
# 3. Run migrations against the container
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _run_migrations(
    postgres_container: PostgresContainer,
    _set_test_env: None,  # ensure env is set first
) -> None:
    """Apply SQL migration files from the ``migrations/`` directory.

    Reads every ``.sql`` file in alphabetical order and executes it
    against the Testcontainers Postgres instance.

    Args:
        postgres_container: The running Testcontainers Postgres instance.
        _set_test_env: Ensures environment variables are configured first.
    """
    import pathlib

    migrations_dir = (
        pathlib.Path(__file__).resolve().parent.parent.parent / "migrations"
    )
    if not migrations_dir.exists():
        pytest.fail(
            f"Migrations directory not found: {migrations_dir}. "
            "Tests require migration SQL files to set up the database schema."
        )

    dsn = _make_dsn(postgres_container)
    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            conn.execute(sql_file.read_text())


# Reuse the session-scoped postgres_container for override_get_db


@pytest.fixture(scope="module")
def override_get_db(postgres_container):
    dsn = _make_dsn(postgres_container)

    def _get_db() -> typing.Generator[Cursor, None, None]:
        with connect(dsn) as conn:
            with conn.cursor() as cursor:
                yield cursor

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(override_get_db):
    with TestClient(app) as c:
        yield c


# Per-test db_session fixture for psycopg cursor with rollback
@pytest.fixture
def db_session(postgres_container) -> typing.Generator[Cursor, None, None]:
    dsn = _make_dsn(postgres_container)
    with connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cursor:
            try:
                yield cursor
            finally:
                conn.rollback()
