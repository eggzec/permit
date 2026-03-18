from datetime import timedelta
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from faker import Faker
from psycopg import Connection
from uuid6 import uuid7

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


fake = Faker()

# ---------------------------------------------------------------------------
# Pure unit tests — no DB required
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_hash_and_verify():
    plain = fake.password(length=12)
    hashed = get_password_hash(plain)

    assert hashed != plain, "Hash must not be the plaintext password"
    assert hashed.startswith("$2"), "Hash must use bcrypt ($2… prefix)"
    valid, _ = verify_password(plain, hashed)
    assert valid is True, "Correct password must verify successfully"


@pytest.mark.unit
def test_wrong_password_fails():
    hashed = get_password_hash(fake.password())
    valid, _ = verify_password(fake.password(), hashed)
    assert valid is False, "Wrong password must not verify"


@pytest.mark.unit
def test_access_token_claims(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_access_token(vendor_id, app_settings)

    payload = decode_token(token, app_settings)
    assert payload["vendor_id"] == vendor_id, "Token must encode vendor_id"
    assert payload["token_type"] == "access", (
        "Access tokens must have type 'access'"
    )
    assert "exp" in payload, "Token must have an expiry claim"


@pytest.mark.unit
def test_refresh_token_claims(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_refresh_token(vendor_id, app_settings)

    payload = decode_token(token, app_settings)
    assert payload["vendor_id"] == vendor_id, "Token must encode vendor_id"
    assert payload["token_type"] == "refresh", (
        "Refresh tokens must have type 'refresh'"
    )
    assert "exp" in payload, "Token must have an expiry claim"


@pytest.mark.unit
def test_expired_token_raises(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_access_token(
        vendor_id, app_settings, expires_delta=timedelta(seconds=-1)
    )

    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(token, app_settings)


@pytest.mark.unit
def test_invalid_signature_raises(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_access_token(vendor_id, app_settings)

    bad_settings = Settings(
        SECRET_KEY=fake.password(length=32),
        PROJECT_NAME="test",
        POSTGRES_SERVER="localhost",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="test",
    )
    with pytest.raises(pyjwt.InvalidSignatureError):
        decode_token(token, bad_settings)


@pytest.mark.unit
def _make_creds(token: str):
    creds = MagicMock()
    creds.credentials = token
    return creds


@pytest.mark.unit
def test_valid_access_token(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_access_token(vendor_id, app_settings)
    result = get_current_vendor_id(_make_creds(token), app_settings)
    assert result == vendor_id, "Must return the encoded vendor_id"


@pytest.mark.unit
def test_missing_credentials_raises(app_settings: Settings):
    with pytest.raises(AuthenticationException, match="Missing"):
        get_current_vendor_id(None, app_settings)


@pytest.mark.unit
def test_refresh_token_rejected(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_refresh_token(vendor_id, app_settings)
    with pytest.raises(AuthenticationException, match="Invalid token type"):
        get_current_vendor_id(_make_creds(token), app_settings)


@pytest.mark.unit
def test_expired_token_raises_dep(app_settings: Settings):
    vendor_id = str(uuid7())
    token = create_access_token(
        vendor_id, app_settings, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(AuthenticationException):
        get_current_vendor_id(_make_creds(token), app_settings)


@pytest.mark.unit
def test_garbage_token_raises(app_settings: Settings):
    with pytest.raises(AuthenticationException):
        get_current_vendor_id(_make_creds("not.a.jwt"), app_settings)


@pytest.mark.unit
def test_malformed_vendor_id_raises(app_settings: Settings):
    token = create_access_token("invalid-uuid", app_settings)
    with pytest.raises(AuthenticationException, match="Invalid token payload"):
        get_current_vendor_id(_make_creds(token), app_settings)


# ---------------------------------------------------------------------------
# Service tests — real transactional DB, no patching
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_signup_success(db_conn: Connection, app_settings: Settings):
    with db_conn.cursor() as db_cursor:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        result = signup(db_cursor, email, password, client_id, app_settings)

        assert result.vendor.email == email, "Returned email must match"
        assert result.vendor.id, "Created vendor must have an id"


@pytest.mark.integration
def test_signup_duplicate_email_raises(
    db_conn: Connection, app_settings: Settings
):
    with db_conn.cursor() as db_cursor:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        signup(db_cursor, email, password, client_id, app_settings)

        with pytest.raises(ConflictException):
            signup(db_cursor, email, password, client_id, app_settings)


@pytest.mark.integration
def test_login_success(db_conn: Connection, app_settings: Settings):
    with db_conn.cursor() as db_cursor:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        signup(db_cursor, email, password, client_id, app_settings)

        result = login(db_cursor, email, password, client_id, app_settings)

        assert result.access_token, "login must return an access token"
        assert result.refresh_token, "login must return a refresh token"
        assert result.token_type == "bearer", "token_type must be 'bearer'"

        payload = decode_token(result.access_token, app_settings)
        assert payload["token_type"] == "access", (
            "access token must carry 'access' type"
        )


@pytest.mark.integration
def test_login_wrong_email_raises(db_conn: Connection, app_settings: Settings):
    with db_conn.cursor() as db_cursor:
        with pytest.raises(AuthenticationException):
            login(
                db_cursor,
                fake.email(),
                fake.password(),
                str(uuid7()),
                app_settings,
            )


@pytest.mark.integration
def test_login_wrong_password_raises(
    db_conn: Connection, app_settings: Settings
):
    with db_conn.cursor() as db_cursor:
        email = fake.email()
        correct_password = fake.password()
        wrong_password = fake.password()
        client_id = str(uuid7())
        signup(db_cursor, email, correct_password, client_id, app_settings)

        with pytest.raises(AuthenticationException):
            login(db_cursor, email, wrong_password, client_id, app_settings)


@pytest.mark.integration
def test_refresh_success(db_conn: Connection, app_settings: Settings):
    with db_conn.cursor() as db_cursor:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        signup(db_cursor, email, password, client_id, app_settings)
        tokens = login(db_cursor, email, password, client_id, app_settings)

        result = refresh(
            tokens.refresh_token, client_id, db_cursor, app_settings
        )

        assert result.access_token, "refresh must return a new access token"
        assert result.refresh_token, "refresh must return a new refresh token"


@pytest.mark.integration
def test_refresh_with_access_token_raises(
    db_conn: Connection, app_settings: Settings
):
    with db_conn.cursor() as db_cursor:
        vendor_id = str(uuid7())
        at = create_access_token(vendor_id, app_settings)

        with pytest.raises(AuthenticationException, match="Invalid token type"):
            refresh(at, str(uuid7()), db_cursor, app_settings)


@pytest.mark.integration
def test_refresh_expired_raises(db_conn: Connection, app_settings: Settings):
    with db_conn.cursor() as db_cursor:
        vendor_id = str(uuid7())
        rt = create_refresh_token(
            vendor_id, app_settings, expires_delta=timedelta(seconds=-1)
        )

        with pytest.raises(AuthenticationException):
            refresh(rt, str(uuid7()), db_cursor, app_settings)


@pytest.mark.integration
def test_refresh_deleted_vendor_raises(
    db_conn: Connection, app_settings: Settings
):
    with db_conn.cursor() as db_cursor:
        # Create a refresh token for a vendor that was never inserted
        phantom_vendor_id = str(uuid7())
        rt = create_refresh_token(phantom_vendor_id, app_settings)

        with pytest.raises(AuthenticationException, match="Vendor not found"):
            refresh(rt, str(uuid7()), db_cursor, app_settings)


@pytest.mark.integration
def test_signup_concurrent_insert_conflict_branch(app_settings: Settings):
    """signup() must raise ConflictException when create_vendor returns None."""
    cursor = MagicMock()
    email = fake.email()
    password = fake.password()
    client_id = str(uuid7())

    get_by_email_mock = MagicMock(return_value=None)
    hash_mock = MagicMock(return_value="hashed-password")
    create_vendor_mock = MagicMock(return_value=None)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.services.auth.get_vendor_by_email", get_by_email_mock)
        mp.setattr("app.services.auth.get_password_hash", hash_mock)
        mp.setattr("app.services.auth.create_vendor", create_vendor_mock)

        with pytest.raises(ConflictException, match="already exists"):
            signup(cursor, email, password, client_id, app_settings)

    assert get_by_email_mock.call_count == 1, (
        "signup must check for an existing vendor before insert"
    )
    assert get_by_email_mock.call_args.args == (cursor, email), (
        "signup must query existing vendor using the signup email"
    )
    assert hash_mock.call_count == 1, (
        "signup must hash the provided password before insert attempt"
    )
    assert hash_mock.call_args.args == (password,), (
        "signup must pass the original password to get_password_hash"
    )
    assert create_vendor_mock.call_count == 1, (
        "signup must attempt create_vendor once after hashing"
    )
    assert create_vendor_mock.call_args.args == (
        cursor,
        email,
        "hashed-password",
    ), "signup must call create_vendor with cursor, email, and hashed password"


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload, expected_msg",
    [
        pytest.param(
            {"token_type": "refresh"},
            "Invalid token payload",
            id="missing-vendor-id",
        ),
        pytest.param(
            {"token_type": "refresh", "vendor_id": "not-a-uuid"},
            "Invalid token payload",
            id="malformed-vendor-id",
        ),
    ],
)
def test_refresh_token_payload_errors(app_settings, payload, expected_msg):
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "app.services.auth.decode_token", lambda tok, settings_obj: payload
        )
        with pytest.raises(AuthenticationException, match=expected_msg):
            refresh("fake-token", str(uuid7()), MagicMock(), app_settings)


@pytest.mark.unit
def test_login_persists_upgraded_hash(app_settings):
    # Mock vendor with a generic hash
    vendor = {
        "id": str(uuid7()),
        "email": "test@example.com",
        "password_hash": "old-hash",
    }

    cursor = MagicMock()
    # Mocking get_vendor_by_email to return our vendor
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "app.services.auth.get_vendor_by_email", lambda cur, email: vendor
        )
        # Mock verify_password to return (True, "new-hash") indicating an upgrade is needed
        mp.setattr(
            "app.services.auth.verify_password",
            lambda pwd, hsh: (True, "new-hash"),
        )

        login(
            cursor, "test@example.com", "password", str(uuid7()), app_settings
        )

    # Verify UPDATE was called
    assert cursor.execute.called, (
        "login must persist upgraded password hashes when verify_password "
        "returns an updated hash"
    )
    args, _ = cursor.execute.call_args
    assert 'UPDATE app."vendors"' in args[0], (
        "login must execute an UPDATE statement on app.vendors"
    )
    assert "new-hash" in args[1], (
        "login must write the upgraded hash returned by verify_password"
    )
