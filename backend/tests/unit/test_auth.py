"""Unit tests for JWT-based vendor authentication.

Tests cover:
- Password hashing (bcrypt)
- Token creation and decoding
- Auth service logic (signup, login, refresh)
- Auth dependency (JWT validation)
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest

from app.api.deps import get_current_vendor_id
from app.core.config import Settings
from app.core.exceptions import AuthenticationException, ConflictException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.services.auth import login, refresh, signup


@pytest.fixture
def settings() -> Settings:
    """Minimal settings for security tests."""
    return Settings(
        SECRET_KEY="test-secret-key-for-unit-tests",
        PROJECT_NAME="test",
        POSTGRES_SERVER="localhost",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="test",
        ACCESS_TOKEN_EXPIRE_MINUTES=60,
        REFRESH_TOKEN_EXPIRE_DAYS=7,
    )


@pytest.mark.unit
class TestPasswordHashing:
    def test_hash_and_verify(self):
        plain = "SuperSecret123!"
        hashed = get_password_hash(plain)

        assert hashed != plain
        assert hashed.startswith("$2")  # bcrypt prefix
        valid, _ = verify_password(plain, hashed)
        assert valid is True

    def test_wrong_password_fails(self):
        hashed = get_password_hash("correct-password")
        valid, _ = verify_password("wrong-password", hashed)
        assert valid is False


@pytest.mark.unit
class TestTokens:
    def test_access_token_claims(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_access_token(vendor_id, settings)

        payload = decode_token(token, settings)
        assert payload["vendor_id"] == vendor_id
        assert payload["token_type"] == "access"
        assert "exp" in payload

    def test_refresh_token_claims(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_refresh_token(vendor_id, settings)

        payload = decode_token(token, settings)
        assert payload["vendor_id"] == vendor_id
        assert payload["token_type"] == "refresh"
        assert "exp" in payload

    def test_expired_token_raises(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_access_token(
            vendor_id, settings, expires_delta=timedelta(seconds=-1)
        )

        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(token, settings)

    def test_invalid_signature_raises(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_access_token(vendor_id, settings)

        bad_settings = Settings(
            SECRET_KEY="different-secret",
            PROJECT_NAME="test",
            POSTGRES_SERVER="localhost",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
        )
        with pytest.raises(pyjwt.InvalidSignatureError):
            decode_token(token, bad_settings)


@pytest.mark.unit
class TestAuthService:
    """Test auth service with mocked CRUD layer."""

    def test_signup_success(self, settings: Settings):
        cursor = MagicMock()
        vendor_id = str(uuid.uuid4())

        with (
            patch("app.services.auth.get_vendor_by_email", return_value=None),
            patch(
                "app.services.auth.create_vendor",
                return_value={"id": vendor_id, "email": "v@test.com"},
            ),
        ):
            result = signup(
                cursor, "v@test.com", "password123", "client-1", settings
            )

        assert result.vendor.id == vendor_id
        assert result.vendor.email == "v@test.com"

    def test_signup_duplicate_email_raises(self, settings: Settings):
        cursor = MagicMock()

        with patch(
            "app.services.auth.get_vendor_by_email",
            return_value={
                "id": "x",
                "email": "v@test.com",
                "password_hash": "h",
            },
        ):
            with pytest.raises(ConflictException):
                signup(
                    cursor, "v@test.com", "password123", "client-1", settings
                )

    def test_login_success(self, settings: Settings):
        cursor = MagicMock()
        vendor_id = str(uuid.uuid4())
        hashed = get_password_hash("password123")

        with patch(
            "app.services.auth.get_vendor_by_email",
            return_value={
                "id": vendor_id,
                "email": "v@test.com",
                "password_hash": hashed,
            },
        ):
            result = login(
                cursor, "v@test.com", "password123", "client-1", settings
            )

        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

        payload = decode_token(result.access_token, settings)
        assert payload["vendor_id"] == vendor_id
        assert payload["token_type"] == "access"

    def test_login_wrong_email_raises(self, settings: Settings):
        cursor = MagicMock()

        with patch("app.services.auth.get_vendor_by_email", return_value=None):
            with pytest.raises(AuthenticationException):
                login(
                    cursor, "bad@test.com", "password123", "client-1", settings
                )

    def test_login_wrong_password_raises(self, settings: Settings):
        cursor = MagicMock()
        hashed = get_password_hash("correct-password")

        with patch(
            "app.services.auth.get_vendor_by_email",
            return_value={
                "id": "x",
                "email": "v@test.com",
                "password_hash": hashed,
            },
        ):
            with pytest.raises(AuthenticationException):
                login(
                    cursor, "v@test.com", "wrong-password", "client-1", settings
                )

    def test_refresh_success(self, settings: Settings):
        cursor = MagicMock()
        vendor_id = str(uuid.uuid4())
        rt = create_refresh_token(vendor_id, settings)

        with patch(
            "app.services.auth.get_vendor_by_id",
            return_value={"id": vendor_id, "email": "v@test.com"},
        ):
            result = refresh(rt, "client-1", cursor, settings)

        assert result.access_token
        assert result.refresh_token

    def test_refresh_with_access_token_raises(self, settings: Settings):
        cursor = MagicMock()
        vendor_id = str(uuid.uuid4())
        at = create_access_token(vendor_id, settings)

        with pytest.raises(AuthenticationException, match="Invalid token type"):
            refresh(at, "client-1", cursor, settings)

    def test_refresh_expired_raises(self, settings: Settings):
        cursor = MagicMock()
        vendor_id = str(uuid.uuid4())
        rt = create_refresh_token(
            vendor_id, settings, expires_delta=timedelta(seconds=-1)
        )

        with pytest.raises(AuthenticationException):
            refresh(rt, "client-1", cursor, settings)

    def test_refresh_deleted_vendor_raises(self, settings: Settings):
        cursor = MagicMock()
        vendor_id = str(uuid.uuid4())
        rt = create_refresh_token(vendor_id, settings)

        with patch("app.services.auth.get_vendor_by_id", return_value=None):
            with pytest.raises(
                AuthenticationException, match="Vendor not found"
            ):
                refresh(rt, "client-1", cursor, settings)

    def test_signup_concurrent_insert_conflict(self, settings: Settings):
        """Pre-read shows no existing vendor, but the insert collides
        (create_vendor returns None due to ON CONFLICT DO NOTHING).
        """
        cursor = MagicMock()

        with (
            patch("app.services.auth.get_vendor_by_email", return_value=None),
            patch("app.services.auth.create_vendor", return_value=None),
        ):
            with pytest.raises(ConflictException):
                signup(
                    cursor, "race@test.com", "password123", "client-1", settings
                )


@pytest.mark.unit
class TestGetCurrentVendorId:
    def test_valid_access_token(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_access_token(vendor_id, settings)
        creds = MagicMock()
        creds.credentials = token

        result = get_current_vendor_id(creds, settings)
        assert result == vendor_id

    def test_missing_credentials_raises(self, settings: Settings):
        with pytest.raises(AuthenticationException, match="Missing"):
            get_current_vendor_id(None, settings)

    def test_refresh_token_rejected(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_refresh_token(vendor_id, settings)
        creds = MagicMock()
        creds.credentials = token

        with pytest.raises(AuthenticationException, match="Invalid token type"):
            get_current_vendor_id(creds, settings)

    def test_expired_token_raises(self, settings: Settings):
        vendor_id = str(uuid.uuid4())
        token = create_access_token(
            vendor_id, settings, expires_delta=timedelta(seconds=-1)
        )
        creds = MagicMock()
        creds.credentials = token

        with pytest.raises(AuthenticationException):
            get_current_vendor_id(creds, settings)

    def test_garbage_token_raises(self, settings: Settings):
        creds = MagicMock()
        creds.credentials = "not.a.jwt"

        with pytest.raises(AuthenticationException):
            get_current_vendor_id(creds, settings)

    def test_malformed_vendor_id_raises(self, settings: Settings):
        token = create_access_token("invalid-uuid", settings)
        creds = MagicMock()
        creds.credentials = token

        with pytest.raises(
            AuthenticationException, match="Invalid token payload"
        ):
            get_current_vendor_id(creds, settings)
