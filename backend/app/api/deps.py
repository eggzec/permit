from collections.abc import Generator
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import Cursor

from app.core.config import Settings
from app.core.exceptions import AuthenticationException, ServiceUnavailableException
from app.core.security import decode_token

# ── Re-usable bearer scheme (auto-documents in OpenAPI) ──────
_bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Generator[Cursor, None, None]:
    """Return a database cursor for the request."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ServiceUnavailableException("Database pool not initialized")
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            yield cursor


def get_settings(request: Request) -> Settings:
    """Return settings from app state."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise ServiceUnavailableException("Settings not initialized")
    return settings


CursorDep = Annotated[Cursor, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_current_vendor_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
    settings: SettingsDep,
) -> str:
    """Extract and validate vendor_id from the Authorization: Bearer token.

    Raises AuthenticationException on missing / invalid / expired tokens
    or if the token is not an access token.
    """
    if credentials is None:
        raise AuthenticationException("Missing authentication token")

    try:
        payload = decode_token(credentials.credentials, settings)
    except pyjwt.PyJWTError:
        raise AuthenticationException("Invalid or expired token")

    if payload.get("token_type") != "access":
        raise AuthenticationException("Invalid token type")

    vendor_id: str | None = payload.get("vendor_id")
    if vendor_id is None:
        raise AuthenticationException("Invalid token payload")

    return vendor_id


def get_rls_cursor(
    request: Request,
    vendor_id: Annotated[str, Depends(get_current_vendor_id)],
) -> Generator[Cursor, None, None]:
    """Return a database cursor with app.vendor_id set for RLS.

    After authentication, this dependency:
    1. Obtains a connection from the pool
    2. Calls app.set_app_context(vendor_id) to set the RLS context
    3. Yields the cursor for use in route handlers
    """
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ServiceUnavailableException("Database pool not initialized")
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT app.set_app_context(%s)", (vendor_id,))
            yield cursor


CurrentVendorId = Annotated[str, Depends(get_current_vendor_id)]
RLSCursorDep = Annotated[Cursor, Depends(get_rls_cursor)]
