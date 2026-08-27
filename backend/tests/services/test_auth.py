from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from psycopg import Connection
from pwdlib.hashers import argon2

from app.core.config import Settings
from app.core.exceptions import AuthenticationException, ConflictException
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.services.auth import login, refresh, signup


def build_signup_args(faker) -> tuple[str, str, str]:
    """
    Builds signup credentials and client identity for auth service tests.

    Used by:
        test_signup_success - supplies the happy-path signup inputs.
        test_signup_duplicate_email_raises_conflict - provisions the original and duplicate signup inputs.
        test_login_success_returns_access_and_refresh_tokens - provisions a vendor before login.
        test_login_rejects_invalid_credentials - supplies the baseline valid credentials before one field is varied.
        test_login_persists_upgraded_hash - creates the legacy-hash vendor credentials.
        test_refresh_success_returns_new_token_pair - provisions the vendor and client id used for refresh.

    Args:
        faker: `Faker` session fixture used to generate auth field values.

    Returns:
        tuple[str, str, str]: A unique email, plaintext password, and client id.
    """
    return (
        faker.email(),
        faker.password(length=16, special_chars=True),
        faker.uuid4(),
    )


def build_refresh_payload(faker, **overrides: str) -> dict[str, str | datetime]:
    """
    Builds a refresh-token payload for auth service boundary tests.

    Used by:
        test_refresh_rejects_invalid_tokens - creates malformed and unknown-vendor refresh payloads.
        test_refresh_rejects_missing_vendor_id_claim - creates a signed refresh token with a missing vendor id claim.

    Args:
        faker: `Faker` session fixture used to generate a vendor id.
        overrides: Payload field replacements applied on top of the default refresh-token claims.

    Returns:
        dict[str, str | datetime]: A refresh-token payload containing token type, vendor id, and expiry claims.
    """
    payload: dict[str, str | datetime] = {
        "token_type": "refresh",
        "vendor_id": faker.uuid4(),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_signup_success(
    db_conn: Connection, app_settings: Settings, faker
) -> None:
    """
    Verifies that `app.services.auth.signup` creates a vendor and returns the created vendor in the service response.
    This matters because the auth service is the business-layer contract behind the public signup route.

    Covers:
        - `app.services.auth.signup`

    Rationale:
        The test uses a real transactional database cursor because signup correctness depends on persisted vendor state.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used for auth service configuration.
        faker: Session-scoped `Faker` instance used to generate signup inputs.
    """
    email, password, client_id = build_signup_args(faker)
    with db_conn.cursor() as db_cursor:
        result = signup(db_cursor, email, password, client_id, app_settings)

    assert result.vendor.email == email, (
        f"Expected created vendor email '{email}', got '{result.vendor.email}'"
    )
    assert result.vendor.id, "Expected signup to return a persisted vendor id"


@pytest.mark.integration
def test_signup_duplicate_email_raises_conflict(
    db_conn: Connection, app_settings: Settings, faker
) -> None:
    """
    Verifies that `app.services.auth.signup` raises a conflict when a vendor with the same email already exists.
    This matters because duplicate vendor creation must be rejected before callers issue tokens or create parallel accounts.

    Covers:
        - `app.services.auth.signup`

    Rationale:
        The service is exercised twice against the same transactional cursor so the duplicate path is proven with real database state instead of patched collaborators.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used for auth service configuration.
        faker: Session-scoped `Faker` instance used to generate signup inputs.
    """
    email, password, client_id = build_signup_args(faker)
    with db_conn.cursor() as db_cursor:
        signup(db_cursor, email, password, client_id, app_settings)

        with pytest.raises(
            ConflictException, match="A vendor with this email already exists"
        ):
            signup(db_cursor, email, password, client_id, app_settings)


@pytest.mark.integration
def test_login_success_returns_access_and_refresh_tokens(
    db_conn: Connection, app_settings: Settings, faker
) -> None:
    """
    Verifies that `app.services.auth.login` returns a bearer token pair for valid credentials.
    This matters because the auth service is responsible for issuing the tokens consumed by the API layer.

    Covers:
        - `app.services.auth.login`
        - `app.core.security.decode_token`

    Rationale:
        The test signs up a real vendor first and decodes the issued access token to confirm the service minted the expected token type.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used to sign and decode tokens.
        faker: Session-scoped `Faker` instance used to generate auth inputs.
    """
    email, password, client_id = build_signup_args(faker)
    with db_conn.cursor() as db_cursor:
        signup(db_cursor, email, password, client_id, app_settings)
        result = login(db_cursor, email, password, client_id, app_settings)

    payload = decode_token(result.access_token, app_settings)
    assert result.access_token, (
        "Expected login to return a non-empty access token"
    )
    assert result.refresh_token, (
        "Expected login to return a non-empty refresh token"
    )
    assert result.token_type == "bearer", (
        f"Expected token_type 'bearer', got '{result.token_type}'"
    )
    assert payload["token_type"] == "access", (
        f"Expected access token payload type 'access', got '{payload['token_type']}'"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("use_unknown_email", "use_wrong_password"),
    [
        pytest.param(True, False, id="unknown_email"),
        pytest.param(False, True, id="wrong_password"),
    ],
)
def test_login_rejects_invalid_credentials(
    db_conn: Connection,
    app_settings: Settings,
    faker,
    *,
    use_unknown_email: bool,
    use_wrong_password: bool,
) -> None:
    """
    Verifies that `app.services.auth.login` rejects unknown-email and wrong-password attempts with the same authentication error.
    This matters because the service must enforce credential validation consistently regardless of which input field is wrong.

    Covers:
        - `app.services.auth.login`

    Rationale:
        A single parametrized test varies one credential dimension at a time while keeping the persisted vendor state constant.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used by the auth service.
        faker: Session-scoped `Faker` instance used to generate valid and alternate credentials.

    Parametrize:
        use_unknown_email: Whether the service call swaps in an email that does not exist.
        use_wrong_password: Whether the service call swaps in an incorrect password.
        Cases:
            - <id="unknown_email"> — uses an unrecognized email with the correct password.
            - <id="wrong_password"> — uses the persisted email with an incorrect password.
    """
    email, password, client_id = build_signup_args(faker)
    alternate_email = faker.email()
    alternate_password = faker.password(length=16, special_chars=True)
    with db_conn.cursor() as db_cursor:
        signup(db_cursor, email, password, client_id, app_settings)

        with pytest.raises(
            AuthenticationException, match="Invalid credentials"
        ):
            login(
                db_cursor,
                alternate_email if use_unknown_email else email,
                alternate_password if use_wrong_password else password,
                client_id,
                app_settings,
            )


@pytest.mark.integration
def test_login_persists_upgraded_hash(
    db_conn: Connection, app_settings: Settings, faker
) -> None:
    """
    Verifies that `app.services.auth.login` upgrades a legacy password hash in storage after a successful login.
    This matters because the service is responsible for migrating old password hashes to the preferred format during authentication.

    Covers:
        - `app.services.auth.login`
        - `app.core.security.verify_password`

    Rationale:
        This test uses a real vendor row with an Argon2 legacy hash so the persistence side effect is verified against the database rather than patched lookup helpers. This shape came from REM-004.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used by the auth service.
        faker: Session-scoped `Faker` instance used to generate auth inputs.
    """
    email, password, client_id = build_signup_args(faker)
    legacy_hash = argon2.Argon2Hasher().hash(password)
    with db_conn.cursor() as db_cursor:
        db_cursor.execute(
            """
            INSERT INTO app."vendors" ("email", "password_hash")
            VALUES (%s, %s)
            RETURNING "id"
            """,
            (email, legacy_hash),
        )
        vendor_id = str(db_cursor.fetchone()[0])

        result = login(db_cursor, email, password, client_id, app_settings)
        db_cursor.execute(
            'SELECT "password_hash" FROM app."vendors" WHERE "id" = %s',
            (vendor_id,),
        )
        upgraded_hash = db_cursor.fetchone()[0]

    valid, updated_hash = verify_password(password, upgraded_hash)
    assert result.access_token, (
        "Expected login to succeed after upgrading a legacy password hash"
    )
    assert upgraded_hash != legacy_hash, (
        "Expected login to replace the legacy hash with the preferred hash format"
    )
    assert valid is True, (
        "Expected upgraded password hash to verify successfully"
    )
    assert updated_hash is None, (
        "Expected preferred password hashes to require no further upgrade"
    )


@pytest.mark.integration
def test_refresh_success_returns_new_token_pair(
    db_conn: Connection, app_settings: Settings, faker
) -> None:
    """
    Verifies that `app.services.auth.refresh` exchanges a valid refresh token for a replacement token pair.
    This matters because the auth service owns the token-refresh contract used by the API route.

    Covers:
        - `app.services.auth.login`
        - `app.services.auth.refresh`

    Rationale:
        The test performs the full signup-login-refresh sequence through the real service functions because refresh correctness depends on issued token state.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used to sign and decode tokens.
        faker: Session-scoped `Faker` instance used to generate auth inputs.
    """
    email, password, client_id = build_signup_args(faker)
    with db_conn.cursor() as db_cursor:
        signup(db_cursor, email, password, client_id, app_settings)
        tokens = login(db_cursor, email, password, client_id, app_settings)
        result = refresh(
            tokens.refresh_token, client_id, db_cursor, app_settings
        )

    assert result.access_token, (
        "Expected refresh to return a non-empty replacement access token"
    )
    assert result.refresh_token, (
        "Expected refresh to return a non-empty replacement refresh token"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("token_factory", "expected_message"),
    [
        pytest.param(
            lambda faker, settings: create_access_token(
                faker.uuid4(), settings
            ),
            "Invalid token type",
            id="access_token",
        ),
        pytest.param(
            lambda faker, settings: create_refresh_token(
                faker.uuid4(), settings, expires_delta=timedelta(seconds=-1)
            ),
            "Invalid or expired refresh token",
            id="expired_refresh_token",
        ),
        pytest.param(
            lambda faker, settings: jwt.encode(
                build_refresh_payload(faker, vendor_id=faker.word()),
                settings.SECRET_KEY,
                algorithm=JWT_ALGORITHM,
            ),
            "Invalid token payload",
            id="malformed_vendor_id",
        ),
        pytest.param(
            lambda faker, settings: jwt.encode(
                build_refresh_payload(faker),
                settings.SECRET_KEY,
                algorithm=JWT_ALGORITHM,
            ),
            "Vendor not found",
            id="unknown_vendor",
        ),
    ],
)
def test_refresh_rejects_invalid_tokens(
    db_conn: Connection,
    app_settings: Settings,
    faker,
    token_factory,
    expected_message: str,
) -> None:
    """
    Verifies that `app.services.auth.refresh` rejects invalid refresh tokens, malformed payloads, and unknown-vendor claims.
    This matters because the service must not mint new tokens from unusable or untrusted refresh input.

    Covers:
        - `app.services.auth.refresh`

    Rationale:
        The test signs real token variants instead of patching decode helpers, so it documents the actual service boundary. This shape came from REM-003.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used to sign token variants.
        faker: Session-scoped `Faker` instance used to generate claims and ids.

    Parametrize:
        token_factory: Produces the invalid refresh token variant for the scenario.
        expected_message: The authentication error expected from the service.
        Cases:
            - <id="access_token"> — supplies an access token where a refresh token is required.
            - <id="expired_refresh_token"> — supplies a refresh token whose expiry is already in the past.
            - <id="malformed_vendor_id"> — supplies a refresh token whose vendor id claim is not a UUID.
            - <id="unknown_vendor"> — supplies a refresh token whose vendor id does not exist in the database.
    """
    refresh_token = token_factory(faker, app_settings)
    with db_conn.cursor() as db_cursor:
        with pytest.raises(AuthenticationException, match=expected_message):
            refresh(refresh_token, faker.uuid4(), db_cursor, app_settings)


@pytest.mark.integration
def test_refresh_rejects_missing_vendor_id_claim(
    db_conn: Connection, app_settings: Settings, faker
) -> None:
    """
    Verifies that `app.services.auth.refresh` rejects a refresh token whose vendor id claim is missing.
    This matters because the refresh contract requires a resolvable vendor identity before new tokens can be issued.

    Covers:
        - `app.services.auth.refresh`

    Rationale:
        The test signs a real refresh payload with `vendor_id=None` so the payload-validation branch is exercised without internal patching. This shape came from REM-003.

    Fixtures:
        db_conn: Transactional database connection rolled back after the test.
        app_settings: Shared `Settings` object used to sign the malformed refresh token.
        faker: Session-scoped `Faker` instance used to generate claim values and client id.
    """
    refresh_token = jwt.encode(
        build_refresh_payload(faker, vendor_id=None),
        app_settings.SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    with db_conn.cursor() as db_cursor:
        with pytest.raises(
            AuthenticationException, match="Invalid token payload"
        ):
            refresh(refresh_token, faker.uuid4(), db_cursor, app_settings)
