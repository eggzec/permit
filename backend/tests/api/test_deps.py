from unittest.mock import MagicMock

import pytest
from fastapi import Request

from app.api import deps
from app.core.config import Settings
from app.core.exceptions import (
    AuthenticationException,
    ServiceUnavailableException,
)


@pytest.mark.unit
def test_get_db_yields_cursor_when_pool_exists():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()

    cursor = MagicMock(name="cursor")
    conn = MagicMock(name="connection")
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None

    pool = MagicMock(name="pool")
    pool.connection.return_value.__enter__.return_value = conn
    pool.connection.return_value.__exit__.return_value = None
    request.app.state.db_pool = pool

    generator = deps.get_db(request)
    yielded = next(generator)
    assert yielded is cursor, "get_db must yield the cursor from the pool"

    with pytest.raises(StopIteration, match=""):
        next(generator)

    assert pool.connection.call_count == 1, (
        "get_db must open exactly one pooled connection"
    )
    assert conn.cursor.call_count == 1, (
        "get_db must open exactly one cursor from the pooled connection"
    )


@pytest.mark.unit
def test_get_db_raises_when_pool_missing():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()
    request.app.state.db_pool = None

    with pytest.raises(
        ServiceUnavailableException, match="Database pool not initialized"
    ):
        next(deps.get_db(request))


@pytest.mark.unit
def test_get_settings_raises_when_settings_missing():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()
    request.app.state.settings = None

    with pytest.raises(
        ServiceUnavailableException, match="Settings not initialized"
    ):
        deps.get_settings(request)


@pytest.mark.unit
def test_get_settings_returns_settings_when_present():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()
    settings = MagicMock(spec=Settings)
    request.app.state.settings = settings

    resolved = deps.get_settings(request)
    assert resolved is settings, (
        "get_settings must return the settings object from app state"
    )


@pytest.mark.unit
def test_get_rls_cursor_raises_when_pool_missing():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()
    request.app.state.db_pool = None

    with pytest.raises(
        ServiceUnavailableException, match="Database pool not initialized"
    ):
        next(deps.get_rls_cursor(request, vendor_id="some-id"))


@pytest.mark.unit
def test_get_rls_cursor_sets_context_and_yields_cursor():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()
    vendor_id = "01234567-89ab-cdef-0123-456789abcdef"

    cursor = MagicMock(name="cursor")
    conn = MagicMock(name="connection")
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None

    pool = MagicMock(name="pool")
    pool.connection.return_value.__enter__.return_value = conn
    pool.connection.return_value.__exit__.return_value = None
    request.app.state.db_pool = pool

    generator = deps.get_rls_cursor(request, vendor_id=vendor_id)
    yielded = next(generator)
    assert yielded is cursor, "get_rls_cursor must yield the DB cursor"
    assert cursor.execute.call_count == 1, (
        "get_rls_cursor must set app context exactly once per request"
    )
    assert cursor.execute.call_args.args == (
        "SELECT app.set_app_context(%s)",
        (vendor_id,),
    ), "get_rls_cursor must set app context using the authenticated vendor_id"

    with pytest.raises(StopIteration, match=""):
        next(generator)


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload, expected_msg",
    [
        pytest.param({}, "Invalid token payload", id="missing-vendor-id"),
        pytest.param(
            {"vendor_id": "not-a-uuid"},
            "Invalid token payload",
            id="malformed-vendor-id",
        ),
    ],
)
def test_get_current_vendor_id_payload_errors(payload, expected_msg):
    # Mock credentials and settings
    credentials = MagicMock()
    credentials.credentials = "fake-token"
    settings = MagicMock(spec=Settings)

    # Mock decode_token to return our test payload
    # We must mock the import in app.api.deps
    # We need to add 'token_type': 'access' to make it pass the type check
    effective_payload = dict(payload)
    if "token_type" not in effective_payload:
        effective_payload["token_type"] = "access"

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "app.api.deps.decode_token",
            lambda tok, settings_obj: effective_payload,
        )

        with pytest.raises(AuthenticationException, match=expected_msg):
            deps.get_current_vendor_id(credentials, settings)
