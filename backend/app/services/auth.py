"""Auth service — orchestrates signup, login, and token refresh."""

from __future__ import annotations

import logging

import jwt as pyjwt
from psycopg import Cursor

from app.core.config import Settings
from app.core.exceptions import AuthenticationException, ConflictException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.crud.vendor import create_vendor, get_vendor_by_email, get_vendor_by_id
from app.schemas.auth import SignupResponse, TokenPair, VendorOut

logger = logging.getLogger(__name__)


def signup(
    cursor: Cursor,
    email: str,
    password: str,
    client_id: str,
    settings: Settings,
) -> SignupResponse:
    """Create a new vendor account.

    Raises ConflictException if the email already exists.
    """
    existing = get_vendor_by_email(cursor, email)
    if existing is not None:
        raise ConflictException("A vendor with this email already exists")

    hashed = get_password_hash(password)
    vendor = create_vendor(cursor, email, hashed)

    logger.info("Vendor created: %s (client_id=%s)", vendor["id"], client_id)
    return SignupResponse(vendor=VendorOut(**vendor))


def login(
    cursor: Cursor,
    email: str,
    password: str,
    client_id: str,
    settings: Settings,
) -> TokenPair:
    """Authenticate a vendor and return an access/refresh token pair.

    Raises AuthenticationException for invalid credentials.
    """
    vendor = get_vendor_by_email(cursor, email)
    if vendor is None:
        raise AuthenticationException()

    valid, updated_hash = verify_password(password, vendor["password_hash"])
    if not valid:
        raise AuthenticationException()

    # If the hashing library returned an upgraded hash, persist it
    if updated_hash is not None:
        cursor.execute(
            'UPDATE app."vendors" SET "password_hash" = %s, "updated_at" = NOW() '
            'WHERE "id" = %s',
            (updated_hash, vendor["id"]),
        )

    access_token = create_access_token(vendor["id"], settings)
    refresh_token = create_refresh_token(vendor["id"], settings)

    logger.info("Vendor logged in: %s (client_id=%s)", vendor["id"], client_id)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


def refresh(
    refresh_token_str: str,
    client_id: str,
    cursor: Cursor,
    settings: Settings,
) -> TokenPair:
    """Issue a new token pair from a valid refresh token.

    Raises AuthenticationException if the token is invalid/expired
    or if it is not a refresh token.
    """
    try:
        payload = decode_token(refresh_token_str, settings)
    except pyjwt.PyJWTError:
        raise AuthenticationException("Invalid or expired refresh token")

    if payload.get("token_type") != "refresh":
        raise AuthenticationException("Invalid token type")

    vendor_id = payload.get("vendor_id")
    if vendor_id is None:
        raise AuthenticationException("Invalid token payload")

    # Ensure vendor still exists and is not deleted
    vendor = get_vendor_by_id(cursor, vendor_id)
    if vendor is None:
        raise AuthenticationException("Vendor not found")

    access_token = create_access_token(vendor_id, settings)
    new_refresh_token = create_refresh_token(vendor_id, settings)

    logger.info("Token refreshed for vendor: %s (client_id=%s)", vendor_id, client_id)
    return TokenPair(access_token=access_token, refresh_token=new_refresh_token)
