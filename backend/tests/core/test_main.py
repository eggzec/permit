from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from app import main as app_main


@pytest.mark.unit
def test_custom_generate_unique_id_uses_first_tag():
    route = SimpleNamespace(tags=["auth"], name="signup")
    route_id = app_main.custom_generate_unique_id(route)
    assert route_id == "auth-signup", (
        f"Expected custom id 'auth-signup', got '{route_id}'"
    )


@pytest.mark.unit
def test_custom_generate_unique_id_uses_default_tag_when_missing():
    route = SimpleNamespace(tags=[], name="health")
    route_id = app_main.custom_generate_unique_id(route)
    assert route_id == "default-health", (
        f"Expected custom id 'default-health', got '{route_id}'"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_lifespan_success_sets_state_and_closes_pool():
    settings = SimpleNamespace(
        PROJECT_NAME="unit-project", DATABASE_DSN="postgresql://unit-test"
    )
    pool = MagicMock(name="pool")
    conn = MagicMock(name="connection")
    pool.connection.return_value.__enter__.return_value = conn
    pool.connection.return_value.__exit__.return_value = None

    def _pool_factory(dsn: str):
        assert dsn == str(settings.DATABASE_DSN), (
            "lifespan must create ConnectionPool with settings DATABASE_DSN"
        )
        return pool

    app = FastAPI()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(app_main, "Settings", lambda: settings)
        mp.setattr(app_main, "ConnectionPool", _pool_factory)

        async with app_main.lifespan(app):
            assert app.state.settings is settings, (
                "lifespan must attach settings to app.state.settings"
            )
            assert app.state.db_pool is pool, (
                "lifespan must attach the created pool to app.state.db_pool"
            )
            assert app.title == settings.PROJECT_NAME, (
                "lifespan must set app.title to PROJECT_NAME from settings"
            )

    assert conn.execute.call_count == 1, (
        "lifespan must run exactly one startup connectivity query"
    )
    assert conn.execute.call_args.args == ("SELECT 1",), (
        "lifespan must use `SELECT 1` for the startup connectivity check"
    )
    assert pool.close.call_count == 1, (
        "lifespan must close the pool during shutdown after successful startup"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_lifespan_connection_failure_closes_pool_and_wraps_error():
    settings = SimpleNamespace(
        PROJECT_NAME="unit-project", DATABASE_DSN="postgresql://unit-test"
    )
    pool = MagicMock(name="pool")
    root_error = RuntimeError("cannot connect")
    pool.connection.return_value.__enter__.side_effect = root_error
    pool.connection.return_value.__exit__.return_value = None
    app = FastAPI()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(app_main, "Settings", lambda: settings)
        mp.setattr(app_main, "ConnectionPool", lambda dsn: pool)

        with pytest.raises(
            RuntimeError, match="Database connectivity check failed"
        ) as exc_info:
            async with app_main.lifespan(app):
                pass

    assert exc_info.value.__cause__ is root_error, (
        "lifespan must preserve the original connectivity exception as __cause__"
    )
    assert getattr(app.state, "db_pool", None) is None, (
        "lifespan must not expose db_pool on app.state when startup fails"
    )
    assert pool.close.call_count == 1, (
        "lifespan must close the pool when startup connectivity fails"
    )
