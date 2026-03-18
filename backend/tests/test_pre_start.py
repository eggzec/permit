from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app import pre_start


def build_fake_connection(error: Exception | None = None) -> SimpleNamespace:
    """
    Builds a connection-like object that records executed SQL and can raise a configured error.

    Used by:
        test_init_success_executes_connectivity_check_and_closes_pool - records the bootstrap connectivity query.
        test_init_failure_still_closes_pool - forces the connectivity-check failure path.

    Args:
        error: `Exception | None` raised when `execute` is called, if provided.

    Returns:
        SimpleNamespace: A connection substitute with `error`, `executed`, and `execute` attributes.
    """
    connection = SimpleNamespace(error=error, executed=[])

    def execute(statement: str) -> None:
        if connection.error is not None:
            raise connection.error
        connection.executed.append(statement)

    connection.execute = execute
    return connection


def build_fake_pool(connection: SimpleNamespace) -> SimpleNamespace:
    """
    Builds a pool-like object that yields the provided fake connection and counts close calls.

    Used by:
        test_init_success_executes_connectivity_check_and_closes_pool - supplies the temporary pool used during successful bootstrap.
        test_init_failure_still_closes_pool - supplies the temporary pool closed after the connectivity failure path.

    Args:
        connection: `SimpleNamespace` connection substitute returned by `build_fake_connection`.

    Returns:
        SimpleNamespace: A pool substitute with `connection_instance`, `close_calls`, `connection()`, and `close()` attributes.
    """
    pool = SimpleNamespace(connection_instance=connection, close_calls=0)

    @contextmanager
    def connection_context():
        yield connection

    def close() -> None:
        pool.close_calls += 1

    pool.connection = connection_context
    pool.close = close
    return pool


@pytest.mark.unit
def test_init_success_executes_connectivity_check_and_closes_pool(
    monkeypatch,
) -> None:
    """
    Purpose:
        Verifies that `app.pre_start.init` opens a pool, performs the connectivity check, and closes the temporary pool on success.
        This matters because the pre-start bootstrap path is the application’s startup sanity check before the main process begins serving.

    Covers:
        - `app.pre_start.init`

    Rationale:
        This test monkeypatches `app.pre_start.Settings` and `app.pre_start.ConnectionPool` because the bootstrap constructors are not injectable in the current design. The fake pool makes the connectivity and cleanup behavior observable without opening a real pool. NOTE: This patch is a temporary workaround — see REM-001 and the test review findings for the planned remediation.

    Fixtures:
        monkeypatch: Pytest fixture used to replace `app.pre_start.Settings` and `app.pre_start.ConnectionPool` during the test.

    """
    settings = type(
        "SettingsStub", (), {"DATABASE_DSN": "postgresql://unit-test"}
    )()
    pool = build_fake_pool(build_fake_connection())

    monkeypatch.setattr(pre_start, "Settings", lambda: settings)
    monkeypatch.setattr(pre_start, "ConnectionPool", lambda dsn, open: pool)

    pre_start.init.__wrapped__()

    assert pool.connection_instance.executed == ["SELECT 1"], (
        f"Expected init to execute ['SELECT 1'], got {pool.connection_instance.executed}"
    )
    assert pool.close_calls == 1, (
        f"Expected init to close the temporary pool once, got {pool.close_calls}"
    )


@pytest.mark.unit
def test_init_failure_still_closes_pool(monkeypatch) -> None:
    """
    Purpose:
        Verifies that `app.pre_start.init` still closes the temporary pool when the connectivity check fails.
        This matters because the bootstrap path must not leak pool resources during startup failures.

    Covers:
        - `app.pre_start.init`

    Rationale:
        This test monkeypatches `app.pre_start.Settings` and `app.pre_start.ConnectionPool` because the bootstrap constructors are not injectable in the current design. The fake pool forces the failure path while keeping cleanup behavior observable. NOTE: This patch is a temporary workaround — see REM-001 and the test review findings for the planned remediation.

    Fixtures:
        monkeypatch: Pytest fixture used to replace `app.pre_start.Settings` and `app.pre_start.ConnectionPool` during the test.

    """
    root_error = RuntimeError("db not reachable")
    settings = type(
        "SettingsStub", (), {"DATABASE_DSN": "postgresql://unit-test"}
    )()
    pool = build_fake_pool(build_fake_connection(error=root_error))

    monkeypatch.setattr(pre_start, "Settings", lambda: settings)
    monkeypatch.setattr(pre_start, "ConnectionPool", lambda dsn, open: pool)

    with pytest.raises(RuntimeError, match="db not reachable"):
        pre_start.init.__wrapped__()

    assert pool.close_calls == 1, (
        f"Expected init failure path to close the pool once, got {pool.close_calls}"
    )


@pytest.mark.unit
def test_init_propagates_pool_creation_error(monkeypatch) -> None:
    """
    Purpose:
        Verifies that `app.pre_start.init` propagates pool-construction errors instead of suppressing them.
        This matters because startup should fail loudly when the pool cannot even be created.

    Covers:
        - `app.pre_start.init`

    Rationale:
        This test monkeypatches `app.pre_start.Settings` and `app.pre_start.ConnectionPool` because the bootstrap constructors are not injectable in the current design. The patched constructor raises immediately to isolate the pool-creation error path. NOTE: This patch is a temporary workaround — see REM-001 and the test review findings for the planned remediation.

    Fixtures:
        monkeypatch: Pytest fixture used to replace `app.pre_start.Settings` and `app.pre_start.ConnectionPool` during the test.

    """
    root_error = OSError("constructor failed")
    settings = type(
        "SettingsStub", (), {"DATABASE_DSN": "postgresql://unit-test"}
    )()

    def raise_pool_error(dsn: str, open: bool):
        raise root_error

    monkeypatch.setattr(pre_start, "Settings", lambda: settings)
    monkeypatch.setattr(pre_start, "ConnectionPool", raise_pool_error)

    with pytest.raises(OSError, match="constructor failed"):
        pre_start.init.__wrapped__()


@pytest.mark.unit
def test_main_calls_init(monkeypatch) -> None:
    """
    Purpose:
        Verifies that `app.pre_start.main` delegates directly to `app.pre_start.init`.
        This matters because the module entry point should execute the same bootstrap path as direct calls to `init`.

    Covers:
        - `app.pre_start.main`

    Rationale:
        This test monkeypatches `app.pre_start.init` because the goal is to confirm delegation, not to rerun the bootstrap side effects. NOTE: This patch is a temporary workaround — see REM-001 and the test review findings for the planned remediation.

    Fixtures:
        monkeypatch: Pytest fixture used to replace `app.pre_start.init` during the test.

    """
    calls: list[str] = []

    def fake_init() -> None:
        calls.append("called")

    monkeypatch.setattr(pre_start, "init", fake_init)
    pre_start.main()

    assert calls == ["called"], f"Expected main to call init once, got {calls}"
