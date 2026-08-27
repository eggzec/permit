"""Root conftest — shared fixtures for all backend tests.

Fixture hierarchy
-----------------
pg_container   (session) — one Postgres Testcontainer per session
migrated_db_pool (session) — ConnectionPool over the container
app_settings    (session) — Settings with known test secrets
faker          (session) — reproducible Faker seeded per xdist worker
db_conn          (function) — connection with force_rollback=True (no leaks)
"""

from __future__ import annotations

import os
import shlex
import time
import typing
from pathlib import Path

import pytest
from faker import Faker
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


def xdist_worker_offset() -> int:
    """
    Returns the numeric xdist worker offset used to derive a stable Faker seed.

    Used by:
        faker - offsets the shared base seed so parallel workers do not reuse
        identical fake data streams.


    Returns:
        int: The parsed xdist worker number, or `0` for the master process and
        unknown names.
    """
    worker_name = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    if worker_name == "master":
        return 0
    suffix = worker_name.removeprefix("gw")
    return int(suffix) if suffix.isdigit() else 0


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
    """
    Provides a PostgreSQL Testcontainer with the backend migrations applied.

    Scope: session — the container is expensive to start and tests do not mutate the container definition itself.

    Provides:
        A started `PostgresContainer` whose connection details are exported into the process environment for `Settings`.

    Dependencies:
        None.

    Teardown:
        The context manager stops the container after the test session ends.

    Note:
        This fixture shares the same database container across the session; write isolation must come from `db_conn`, not from restarting the container.
    """
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
    """
    Provides a connection pool bound to the migrated PostgreSQL test container.

    Scope: session — opening the pool is expensive and tests safely share it through function-scoped transactions.

    Provides:
        An open `ConnectionPool` configured against the test container database.

    Dependencies:
        pg_container: Supplies the live PostgreSQL test container and its connection URL.

    Teardown:
        The context manager closes the pool after the session completes.

    Note:
        This fixture is read-write, but individual tests must isolate writes through `db_conn`.
    """
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
    """
    Provides a shared `Settings` instance configured from the test container environment.

    Scope: session — configuration is immutable for the duration of the suite and is safe to reuse.

    Provides:
        A `Settings` object with deterministic test secrets and database connection values.

    Dependencies:
        pg_container: Ensures the environment variables reflect the live container ports and credentials before settings are instantiated.

    Teardown:
        None.

    Note:
        Tests that need per-request database state should not mutate this object.
    """
    return Settings()


@pytest.fixture(scope="session")
def faker() -> Faker:
    """
    Provides a session-scoped Faker instance with a stable worker-aware seed.

    Scope: session — the faker object is reused safely and deterministic seeding is part of the test contract.

    Provides:
        A `Faker` instance seeded from `PYTEST_RANDOMLY_SEED` plus the current xdist worker offset.

    Dependencies:
        None.

    Teardown:
        None.

    Note:
        Parallel workers intentionally receive different offsets so generated values remain reproducible without colliding across workers.
    """
    base_seed = int(os.environ.get("PYTEST_RANDOMLY_SEED", "20260318"))
    seed = base_seed + xdist_worker_offset()
    fake = Faker()
    fake.seed_instance(seed)
    return fake


@pytest.fixture(scope="session", autouse=True)
def setup_session_overrides(app_settings: Settings) -> None:
    """
    Applies the session-wide FastAPI dependency override for shared settings.

    Scope: session — the settings override is immutable and should remain installed for the whole run.

    Provides:
        `None`; it installs `get_settings` into `app.dependency_overrides`.

    Dependencies:
        app_settings: Supplies the shared `Settings` object returned by the dependency override.

    Teardown:
        None.

    Note:
        This fixture mutates global application state once at session start because `get_settings` is not injectable per request in the current test setup.
    """
    app.dependency_overrides[get_settings] = lambda: app_settings


# ---------------------------------------------------------------------------
# Function-scoped: transactional isolation per test
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn(
    migrated_db_pool: ConnectionPool,
) -> typing.Generator[Connection, None, None]:
    """
    Provides a database connection wrapped in an automatic rollback transaction.

    Scope: function — each test needs isolated writes that are rolled back after execution.

    Provides:
        An open `Connection` with `force_rollback=True` active for the duration of the test.

    Dependencies:
        migrated_db_pool: Supplies the shared connection pool used to borrow the test connection.

    Teardown:
        The transaction rolls back and the connection returns to the pool after the fixture yields.

    Note:
        Tests should create cursors from this connection rather than opening new pooled connections directly.
    """
    with migrated_db_pool.connection() as conn:
        with conn.transaction(force_rollback=True):
            yield conn


# ---------------------------------------------------------------------------
# Test-only router (protected endpoint helper for integration tests)
# ---------------------------------------------------------------------------

_test_router = _APIRouter(prefix="/tests")


@_test_router.get("/protected-test")
def protected_test(vendor_id: CurrentVendorId, cursor: RLSCursorDep) -> dict:
    """
    Returns the authenticated vendor id and the database RLS context for protected-route assertions.

    Used by:
        test_missing_token_returns_401 - exercises the authentication boundary for a protected endpoint.
        test_expired_token_returns_401 - verifies expired access tokens are rejected before reaching protected logic.
        test_valid_token_returns_vendor_id - proves the API and database see the same vendor context after authentication.

    Args:
        vendor_id: `str` vendor identifier resolved from the access token dependency.
        cursor: `Cursor` opened through the RLS dependency with tenant context already applied.

    Returns:
        dict: A payload containing the dependency-resolved `vendor_id` and the value stored in `current_setting('app.vendor_id', true)`.
    """
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
def override_function_dependencies(
    db_conn: Connection,
) -> typing.Generator[None, None, None]:
    """
    Applies per-test database dependency overrides that bind FastAPI dependencies to the transactional test connection.

    Scope: function — the overrides capture a function-scoped transaction and must be reset after every test.

    Provides:
        `None`; it temporarily installs `get_db` and `get_rls_cursor` overrides onto the global `app`.

    Dependencies:
        db_conn: Supplies the transactional database connection whose cursors back the overrides.

    Teardown:
        Removes the temporary overrides for `get_db` and `get_rls_cursor` after the test finishes.

    Note:
        This fixture mutates global dependency state because the application dependencies are not injectable without touching `app.dependency_overrides`.
    """

    def get_db_override() -> typing.Generator[Cursor, None, None]:
        """
        Yields a cursor backed by the current test transaction.

        Used by:
            override_function_dependencies - binds FastAPI's `get_db` dependency to the per-test connection.

        Args:
            None.

        Returns:
            typing.Generator[Cursor, None, None]: A cursor created from `db_conn` for one dependency resolution.
        """
        with db_conn.cursor() as cur:
            yield cur

    def get_rls_cursor_override(
        vendor_id: CurrentVendorId,
    ) -> typing.Generator[Cursor, None, None]:
        """
        Yields a cursor after applying the authenticated vendor context to the current transaction.

        Used by:
            override_function_dependencies - binds FastAPI's `get_rls_cursor` dependency to the per-test connection.

        Args:
            vendor_id: `str` vendor identifier to install through `app.set_app_context`.

        Returns:
            typing.Generator[Cursor, None, None]: A cursor with the RLS app context already set for the authenticated vendor.
        """
        with db_conn.cursor() as cur:
            cur.execute("SELECT app.set_app_context(%s)", (vendor_id,))
            yield cur

    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_rls_cursor] = get_rls_cursor_override

    try:
        yield
    finally:
        # Avoid .clear() to preserve session-level overrides
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_rls_cursor, None)
