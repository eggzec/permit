from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app import main as app_main


def build_fake_connection(error: Exception | None = None) -> SimpleNamespace:
    """
    Builds a connection-like object that records executed statements and can raise a configured error.

    Used by:
        test_lifespan_success_sets_state_and_closes_pool - records the startup connectivity query.
        test_lifespan_connection_failure_closes_pool_and_wraps_error - forces the connectivity-check failure path.

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
        test_lifespan_success_sets_state_and_closes_pool - supplies the pool stored on app state during the successful lifespan path.
        test_lifespan_connection_failure_closes_pool_and_wraps_error - supplies the pool closed after a startup failure.

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
@pytest.mark.parametrize(
    "tags,name,expected_route_id",
    [
        pytest.param(["auth"], "signup", "auth-signup", id="tagged_route"),
        pytest.param([], "health", "default-health", id="default_tag"),
    ],
)
def test_custom_generate_unique_id_uses_expected_prefix(
    tags: list[str], name: str, expected_route_id: str
) -> None:
    """
    Purpose:
        Verifies that `app.main.custom_generate_unique_id` prefixes generated route ids with the first tag when present and with `default` otherwise.
        This matters because route ids feed generated OpenAPI operation names and should stay stable across tagged and untagged routes.

    Covers:
        - `app.main.custom_generate_unique_id`

    Rationale:
        The route object is represented with a `SimpleNamespace` because the function depends only on `tags` and `name`.

    Fixtures:
        None.

    Parametrize:
        tags: Route tags presented to the unique-id helper.
        name: Route name presented to the unique-id helper.
        expected_route_id: Expected generated identifier.
        Cases:
            - <id="tagged_route"> — uses the first tag as the route-id prefix.
            - <id="default_tag"> — falls back to `default` when tags are absent.
    """
    route = SimpleNamespace(tags=tags, name=name)
    route_id = app_main.custom_generate_unique_id(route)

    assert route_id == expected_route_id, (
        f"Expected generated route id '{expected_route_id}', got '{route_id}'"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_lifespan_success_sets_state_and_closes_pool(monkeypatch) -> None:
    """
    Purpose:
        Verifies that `app.main.lifespan` stores settings and the database pool on `app.state`, performs a startup connectivity check, and closes the pool on shutdown.
        This matters because application startup must both initialize shared state and clean up resources reliably.

    Covers:
        - `app.main.lifespan`

    Rationale:
        This test monkeypatches `app.main.Settings` and `app.main.ConnectionPool` because startup constructors are not injectable in the current design. The fake pool lets the test assert observable lifespan behavior without opening a real pool. NOTE: This patch is a temporary workaround — see test review findings for the planned remediation.

    Fixtures:
        monkeypatch: Pytest fixture used to replace `app.main.Settings` and `app.main.ConnectionPool` during the test.

    """
    settings = SimpleNamespace(
        PROJECT_NAME="unit-project", DATABASE_DSN="postgresql://unit-test"
    )
    pool = build_fake_pool(build_fake_connection())
    app = FastAPI()

    def build_pool(dsn: str, *, open: bool) -> SimpleNamespace:
        assert dsn == str(settings.DATABASE_DSN), (
            f"Expected ConnectionPool DSN '{settings.DATABASE_DSN}', got '{dsn}'"
        )
        assert open is True, (
            "Expected lifespan to construct ConnectionPool with open=True"
        )
        return pool

    monkeypatch.setattr(app_main, "Settings", lambda: settings)
    monkeypatch.setattr(app_main, "ConnectionPool", build_pool)

    async with app_main.lifespan(app):
        assert app.state.settings is settings, (
            "Expected lifespan to store settings on app.state.settings"
        )
        assert app.state.db_pool is pool, (
            "Expected lifespan to store the database pool on app.state.db_pool"
        )
        assert app.title == settings.PROJECT_NAME, (
            f"Expected app title '{settings.PROJECT_NAME}', got '{app.title}'"
        )

    assert pool.connection_instance.executed == ["SELECT 1"], (
        f"Expected startup connectivity query ['SELECT 1'], got {pool.connection_instance.executed}"
    )
    assert pool.close_calls == 1, (
        f"Expected lifespan shutdown to close the pool once, got {pool.close_calls}"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_lifespan_connection_failure_closes_pool_and_wraps_error(
    monkeypatch,
) -> None:
    """
    Purpose:
        Verifies that `app.main.lifespan` closes the pool and wraps startup connection failures in the expected runtime error.
        This matters because startup failures must preserve the root cause while still cleaning up partially initialized resources.

    Covers:
        - `app.main.lifespan`

    Rationale:
        This test monkeypatches `app.main.Settings` and `app.main.ConnectionPool` because startup constructors are not injectable in the current design. The fake pool forces the failure path without touching real infrastructure. NOTE: This patch is a temporary workaround — see test review findings for the planned remediation.

    Fixtures:
        monkeypatch: Pytest fixture used to replace `app.main.Settings` and `app.main.ConnectionPool` during the test.

    """
    root_error = RuntimeError("cannot connect")
    settings = SimpleNamespace(
        PROJECT_NAME="unit-project", DATABASE_DSN="postgresql://unit-test"
    )
    pool = build_fake_pool(build_fake_connection(error=root_error))
    app = FastAPI()

    monkeypatch.setattr(app_main, "Settings", lambda: settings)
    monkeypatch.setattr(app_main, "ConnectionPool", lambda dsn, *, open: pool)

    with pytest.raises(
        RuntimeError, match="Database connectivity check failed"
    ) as exc_info:
        async with app_main.lifespan(app):
            pass

    assert exc_info.value.__cause__ is root_error, (
        "Expected lifespan to preserve the original connection error as __cause__"
    )
    assert getattr(app.state, "db_pool", None) is None, (
        "Expected failed startup to avoid exposing db_pool on application state"
    )
    assert pool.close_calls == 1, (
        f"Expected failed startup to close the pool once, got {pool.close_calls}"
    )
