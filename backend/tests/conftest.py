"""Root conftest — shared fixtures for all backend tests.

Fixture hierarchy
-----------------
pg_container   (session) — one Postgres Testcontainer per session
migrated_db_pool (session) — ConnectionPool over the container
app_settings    (session) — Settings with known test secrets
db_conn          (function) — connection with force_rollback=True (no leaks)
client           (function) — FastAPI TestClient with dependency overrides
                              pointing at the same transactional db_conn
"""

from __future__ import annotations

import os
import shlex
import time
import typing
from pathlib import Path

import pytest
from fastapi import APIRouter as _APIRouter
from psycopg import Connection, Cursor
from psycopg_pool import ConnectionPool
from testcontainers.core.waiting_utils import WaitStrategy, WaitStrategyTarget
from testcontainers.postgres import PostgresContainer

from app.api.deps import (
    CurrentVendorId,
    RLSCursorDep,
    get_db,
    get_rls_cursor,
    get_settings,
)
from app.core.config import Settings
from app.main import app


MIGRATIONS_DIR = str(Path(__file__).parents[2] / "migrations")
POSTGRES_IMAGE = "postgres:18.2-alpine3.23"
API_V1 = "/api/v1"


# ---------------------------------------------------------------------------
# Wait strategy — mirrors migrations/tests/helpers.PgReadyWaitStrategy
# ---------------------------------------------------------------------------


class PgReadyWaitStrategy(WaitStrategy):
    """Wait until PostgreSQL accepts connections; surface logs on failure."""

    def wait_until_ready(self, container: WaitStrategyTarget) -> None:
        wrapped = container.get_wrapped_container()
        user = container.username
        start = time.time()

        while True:
            if time.time() - start > self._startup_timeout:
                raise TimeoutError(
                    "Postgres did not become ready within "
                    f"{self._startup_timeout}s"
                )

            wrapped.reload()
            state = wrapped.attrs["State"]

            if state["Status"] == "exited" and state["ExitCode"] != 0:
                stdout, stderr = container.get_logs()
                logs = (stdout + stderr).decode(errors="replace").strip()
                raise RuntimeError(
                    f"Postgres container exited with code {state['ExitCode']}\n"
                    f"--- container logs ---\n{logs}"
                )

            result = container.exec(f"pg_isready -U {shlex.quote(user)}")
            if result.exit_code == 0:
                return

            time.sleep(self._poll_interval)


# ---------------------------------------------------------------------------
# Session-scoped: one container + pool for the whole test run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container() -> typing.Generator[PostgresContainer, None, None]:
    """Session: Testcontainers Postgres with all migrations applied."""
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(
            MIGRATIONS_DIR, "/docker-entrypoint-initdb.d", mode="ro"
        )
        .waiting_for(PgReadyWaitStrategy())
    ) as container:
        os.environ["POSTGRES_SERVER"] = str(container.get_container_host_ip())
        os.environ["POSTGRES_PORT"] = str(container.get_exposed_port(5432))
        os.environ["POSTGRES_USER"] = str(container.username)
        os.environ["POSTGRES_PASSWORD"] = str(container.password)
        os.environ["POSTGRES_DB"] = str(container.dbname)
        os.environ["PROJECT_NAME"] = "test"
        os.environ["SECRET_KEY"] = "integration-test-secret-key-32bytes!"
        yield container


@pytest.fixture(scope="session")
def migrated_db_pool(pg_container: PostgresContainer):
    """Session: connection pool over the test container."""
    with ConnectionPool(
        pg_container.get_connection_url(),
        min_size=4,
        max_size=20,
        open=True,
        check=ConnectionPool.check_connection,
    ) as pool:
        yield pool


@pytest.fixture(scope="session")
def app_settings(pg_container: PostgresContainer) -> Settings:
    """Session: shared Settings for test JWTs and config.
    Instantiated after pg_container is ready to ensure environment chemicals (ports) are correct.
    """
    return Settings()


@pytest.fixture(scope="session", autouse=True)
def _setup_session_overrides(app_settings: Settings) -> None:
    """Apply session-wide dependency overrides."""
    app.dependency_overrides[get_settings] = lambda: app_settings


# ---------------------------------------------------------------------------
# Function-scoped: transactional isolation per test
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn(
    migrated_db_pool: ConnectionPool,
) -> typing.Generator[Connection, None, None]:
    """Per-test connection with automatic rollback — prevents data leakage."""
    with migrated_db_pool.connection() as conn:
        with conn.transaction(force_rollback=True):
            yield conn


# ---------------------------------------------------------------------------
# Test-only router (protected endpoint helper for integration tests)
# ---------------------------------------------------------------------------

_test_router = _APIRouter(prefix="/tests")


@_test_router.get("/protected-test")
def _protected_test(vendor_id: CurrentVendorId, cursor: RLSCursorDep) -> dict:
    cursor.execute("SELECT current_setting('app.vendor_id', true)")
    row = cursor.fetchone()
    db_vendor_id = row[0] if row else None
    return {"vendor_id": vendor_id, "db_vendor_id": db_vendor_id}


# Register the test-only router onto the global app once.
app.include_router(_test_router)


# ---------------------------------------------------------------------------
# Function-scoped autouse: Isolated dependencies per test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _override_function_dependencies(
    db_conn: Connection,
) -> typing.Generator[None, None, None]:
    """Automatically applies transactional database overrides to the global `app`."""

    def _get_db() -> typing.Generator[Cursor, None, None]:
        with db_conn.cursor() as cur:
            yield cur

    def _get_rls_cursor(
        vendor_id: CurrentVendorId,
    ) -> typing.Generator[Cursor, None, None]:
        with db_conn.cursor() as cur:
            cur.execute("SELECT app.set_app_context(%s)", (vendor_id,))
            yield cur

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_rls_cursor] = _get_rls_cursor

    try:
        yield
    finally:
        # Avoid .clear() to preserve session-level overrides
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_rls_cursor, None)
