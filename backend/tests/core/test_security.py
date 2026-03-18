from __future__ import annotations

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)


@pytest.mark.unit
def test_get_password_hash_round_trip_verifies_password(faker) -> None:
    """
    Purpose:
        Verifies that `app.core.security.get_password_hash` and `app.core.security.verify_password` work together for the valid-password round trip.
        This matters because the application’s password wrapper contract depends on a stored hash being accepted for the original plaintext.

    Covers:
        - `app.core.security.get_password_hash`
        - `app.core.security.verify_password`

    Rationale:
        This test stays at the project boundary by checking the wrapper round trip instead of asserting on hash-library implementation details. Historical third-party-coupled assertions were removed under REM-012.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate a password value.
    """
    plain_password = faker.password(length=16, special_chars=True)
    hashed_password = get_password_hash(plain_password)
    valid, updated_hash = verify_password(plain_password, hashed_password)

    assert hashed_password != plain_password, (
        "Expected password hashing to produce a value distinct from the plaintext"
    )
    assert valid is True, (
        "Expected hashed password to verify the original plaintext"
    )
    assert updated_hash is None, (
        "Expected a freshly generated password hash to require no upgrade"
    )


@pytest.mark.unit
def test_verify_password_rejects_wrong_password(faker) -> None:
    """
    Purpose:
        Verifies that `app.core.security.verify_password` rejects an incorrect plaintext for a stored hash.
        This matters because invalid credentials must fail cleanly at the password-wrapper boundary.

    Covers:
        - `app.core.security.get_password_hash`
        - `app.core.security.verify_password`

    Rationale:
        The test uses a real hash and a different plaintext so it documents the wrapper behavior without testing the hash library itself.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the original and wrong passwords.
    """
    original_password = faker.password(length=16, special_chars=True)
    wrong_password = faker.password(length=16, special_chars=True)
    hashed_password = get_password_hash(original_password)
    valid, updated_hash = verify_password(wrong_password, hashed_password)

    assert valid is False, (
        "Expected password verification to fail for the wrong input"
    )
    assert updated_hash is None, (
        "Expected failed verification to avoid returning an upgraded hash"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "token_factory,expected_type",
    [
        pytest.param(create_access_token, "access", id="access_token"),
        pytest.param(create_refresh_token, "refresh", id="refresh_token"),
    ],
)
def test_token_round_trip_preserves_vendor_id_and_type(
    app_settings, faker, token_factory, expected_type: str
) -> None:
    """
    Purpose:
        Verifies that tokens issued by the project helpers decode back to the expected vendor id and token type.
        This matters because the application’s auth layer depends on a stable round-trip contract for access and refresh tokens.

    Covers:
        - `app.core.security.create_access_token`
        - `app.core.security.create_refresh_token`
        - `app.core.security.decode_token`

    Rationale:
        This test exercises the project’s token helpers as a boundary round trip instead of asserting on JWT-library internals. Historical third-party-coupled assertions were removed under REM-012.

    Fixtures:
        app_settings: Shared `Settings` object used to sign and decode the test tokens.
        faker: Session-scoped `Faker` instance used to generate the vendor id claim.

    Parametrize:
        token_factory: Selects which project token helper issues the token.
        expected_type: The token type claim expected after decoding.
        Cases:
            - <id="access_token"> — issues an access token and expects the `access` claim.
            - <id="refresh_token"> — issues a refresh token and expects the `refresh` claim.
    """
    vendor_id = faker.uuid4()
    token = token_factory(vendor_id, app_settings)
    payload = decode_token(token, app_settings)

    assert payload["vendor_id"] == vendor_id, (
        f"Expected token payload vendor_id '{vendor_id}', got '{payload['vendor_id']}'"
    )
    assert payload["token_type"] == expected_type, (
        f"Expected token_type '{expected_type}', got '{payload['token_type']}'"
    )
    assert "exp" in payload, (
        "Expected decoded token payload to contain an expiry claim"
    )
