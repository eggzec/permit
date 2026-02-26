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

import os
from collections.abc import AsyncIterator, Iterator

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg_pool import ConnectionPool
from testcontainers.postgres import PostgresContainer


def _make_dsn(container: PostgresContainer) -> str:
    """Build a psycopg3-compatible DSN from a Testcontainers instance.

    Args:
        container: A running PostgresContainer from Testcontainers.

    Returns:
        A connection string compatible with psycopg3.
    """
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return (
        f"postgresql://{container.username}:{container.password}"
        f"@{host}:{port}/{container.dbname}"
    )


# ---------------------------------------------------------------------------
# 1. Testcontainers - session-scoped Postgres
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def postgres_container(request: pytest.FixtureRequest) -> PostgresContainer:
    """Start a PostgreSQL container once for the entire test session.

    The container is stopped automatically via a finalizer when the
    session ends.

    Args:
        request: The pytest fixture request object used for teardown.

    Returns:
        A running PostgresContainer instance.
    """
    container = PostgresContainer("postgres:16-alpine")
    container.start()

    def _stop() -> None:
        container.stop()

    request.addfinalizer(_stop)
    return container


# ---------------------------------------------------------------------------
# 2. Inject test DB settings into environment (before importing app code)
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
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
    os.environ.setdefault("PROJECT_NAME", "permit-test")


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
        return

    dsn = _make_dsn(postgres_container)
    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            conn.execute(sql_file.read_text())


# ---------------------------------------------------------------------------
# 4. FastAPI app fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def app(
    postgres_container: PostgresContainer,
    _run_migrations: None,
    request: pytest.FixtureRequest,
) -> FastAPI:
    """Return the FastAPI application with a test connection pool attached.

    Creates a ``ConnectionPool`` pointing at the Testcontainers Postgres
    and assigns it to ``app.state.db_pool``. The pool is closed via a
    finalizer when the session ends.

    Args:
        postgres_container: The running Testcontainers Postgres instance.
        _run_migrations: Ensures migrations have been applied first.
        request: The pytest fixture request object used for teardown.

    Returns:
        The configured FastAPI application.
    """
    from app.main import app as _app  # imported after env vars are set

    # Build a pool pointing at the Testcontainers Postgres
    dsn = _make_dsn(postgres_container)
    pool = ConnectionPool(dsn, open=True)
    _app.state.db_pool = pool

    def _close_pool() -> None:
        pool.close()

    request.addfinalizer(_close_pool)
    return _app


# ---------------------------------------------------------------------------
# 5. Async HTTP test client
# ---------------------------------------------------------------------------
@pytest.fixture()
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Provide an async HTTP client bound to the test application.

    Uses ``httpx.ASGITransport`` so requests are handled in-process
    without needing a live server.

    Args:
        app: The FastAPI application instance.

    Yields:
        An ``httpx.AsyncClient`` ready to make requests.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# 6. Per-test DB cursor with transactional rollback (full isolation)
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_session(app: FastAPI) -> Iterator[psycopg.Cursor]:
    """Provide a database cursor inside a transaction that auto-rolls back.

    Acquires a connection from the pool, disables autocommit, and yields
    a cursor. After the test (whether it passes or fails) the transaction
    is rolled back and the connection is returned to the pool.

    This guarantees every test starts with a deterministic database state.

    Args:
        app: The FastAPI application whose ``state.db_pool`` is used.

    Yields:
        A ``psycopg.Cursor`` operating inside a single transaction.
    """
    pool: ConnectionPool = app.state.db_pool
    conn = pool.getconn()
    # Disable autocommit so everything runs in one transaction
    conn.autocommit = False
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        conn.rollback()
        cursor.close()
        pool.putconn(conn)
