import pytest
from unittest.mock import MagicMock
from fastapi import Request
from app.api import deps
from app.core.exceptions import (
    ServiceUnavailableException,
    AuthenticationException,
)
from app.core.config import Settings


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
def test_get_rls_cursor_raises_when_pool_missing():
    request = MagicMock(spec=Request)
    request.app.state = MagicMock()
    request.app.state.db_pool = None

    with pytest.raises(
        ServiceUnavailableException, match="Database pool not initialized"
    ):
        next(deps.get_rls_cursor(request, vendor_id="some-id"))


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
    if "token_type" not in payload:
        payload["token_type"] = "access"

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "app.api.deps.decode_token", lambda tok, settings_obj: payload
        )

        with pytest.raises(AuthenticationException, match=expected_msg):
            deps.get_current_vendor_id(credentials, settings)
