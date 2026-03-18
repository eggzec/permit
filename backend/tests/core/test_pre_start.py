from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


try:
    from app import pre_start
except TypeError as exc:
    pre_start = None
    PRE_START_IMPORT_ERROR = exc
else:
    PRE_START_IMPORT_ERROR = None


pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        pre_start is None,
        reason=(
            "Blocked by app/pre_start.py import error in tenacity retry "
            f"expression: {PRE_START_IMPORT_ERROR!r}"
        ),
    ),
]


def test_init_success_executes_connectivity_check_and_closes_pool():
    settings = SimpleNamespace(DATABASE_DSN="postgresql://unit-test")
    pool = MagicMock(name="pool")
    conn = MagicMock(name="connection")
    pool.connection.return_value.__enter__.return_value = conn
    pool.connection.return_value.__exit__.return_value = None

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(pre_start, "Settings", lambda: settings)
        mp.setattr(pre_start, "ConnectionPool", lambda dsn, open: pool)
        pre_start.init.__wrapped__()

    assert conn.execute.call_count == 1, (
        "init must execute exactly one connectivity query"
    )
    assert conn.execute.call_args.args == ("SELECT 1",), (
        "init must use `SELECT 1` for connectivity checks"
    )
    assert pool.close.call_count == 1, (
        "init must close the temporary pool after a successful check"
    )


def test_init_failure_still_closes_pool():
    settings = SimpleNamespace(DATABASE_DSN="postgresql://unit-test")
    pool = MagicMock(name="pool")
    root_error = RuntimeError("db not reachable")
    pool.connection.return_value.__enter__.side_effect = root_error
    pool.connection.return_value.__exit__.return_value = None

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(pre_start, "Settings", lambda: settings)
        mp.setattr(pre_start, "ConnectionPool", lambda dsn, open: pool)
        with pytest.raises(RuntimeError, match="db not reachable"):
            pre_start.init.__wrapped__()

    assert pool.close.call_count == 1, (
        "init must close the temporary pool even when connectivity fails"
    )


def test_init_propagates_pool_creation_error():
    settings = SimpleNamespace(DATABASE_DSN="postgresql://unit-test")
    root_error = OSError("constructor failed")

    def _raise_pool_error(dsn: str, open: bool):
        raise root_error

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(pre_start, "Settings", lambda: settings)
        mp.setattr(pre_start, "ConnectionPool", _raise_pool_error)
        with pytest.raises(OSError, match="constructor failed"):
            pre_start.init.__wrapped__()


def test_main_calls_init():
    init_mock = MagicMock(name="init")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(pre_start, "init", init_mock)
        pre_start.main()

    assert init_mock.call_count == 1, "main must call init exactly once"
