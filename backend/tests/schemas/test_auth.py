from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
    VendorOut,
)


def build_auth_request_payload(faker) -> dict[str, str]:
    """
    Builds a valid auth request payload for schema validation tests.

    Used by:
        test_auth_request_models_accept_valid_payloads - supplies valid input for both auth request models.
        test_signup_request_rejects_invalid_payloads - provides the baseline payload before one field is invalidated.

    Args:
        faker: `Faker` session fixture used to generate realistic auth field values.

    Returns:
        dict[str, str]: A JSON-style payload containing a valid email, password, and client id.
    """
    return {
        "email": faker.email(),
        "password": faker.password(length=16, special_chars=True),
        "client_id": faker.uuid4(),
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "model_class",
    [
        pytest.param(SignupRequest, id="signup_request"),
        pytest.param(LoginRequest, id="login_request"),
    ],
)
def test_auth_request_models_accept_valid_payloads(faker, model_class) -> None:
    """
    Purpose:
        Verifies that `app.schemas.auth.SignupRequest` and `app.schemas.auth.LoginRequest` accept the same valid auth payload shape.
        This matters because both request models define the public input contract for the auth API.

    Covers:
        - `app.schemas.auth.SignupRequest`
        - `app.schemas.auth.LoginRequest`

    Rationale:
        One parametrized test keeps the overlapping request-model contract documented in one place.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate valid auth field values.

    Parametrize:
        model_class: The auth request schema being instantiated.
        Cases:
            - <id="signup_request"> — validates the signup request schema.
            - <id="login_request"> — validates the login request schema.
    """
    payload = build_auth_request_payload(faker)
    model = model_class(**payload)

    assert model.email == payload["email"], (
        f"Expected model email '{payload['email']}', got '{model.email}'"
    )
    assert model.password == payload["password"], (
        f"Expected model password to round-trip, got '{model.password}'"
    )
    assert model.client_id == payload["client_id"], (
        f"Expected model client_id '{payload['client_id']}', got '{model.client_id}'"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario,expected_fields",
    [
        pytest.param("invalid_email", {"email"}, id="invalid_email"),
        pytest.param("short_password", {"password"}, id="short_password"),
        pytest.param(
            "missing_client_id", {"client_id"}, id="missing_client_id"
        ),
    ],
)
def test_signup_request_rejects_invalid_payloads(
    faker, scenario: str, expected_fields: set[str]
) -> None:
    """
    Purpose:
        Verifies that `app.schemas.auth.SignupRequest` rejects invalid email, short-password, and missing-client-id payloads.
        This matters because the signup schema is the first validation boundary for auth input.

    Covers:
        - `app.schemas.auth.SignupRequest`

    Rationale:
        The test mutates one valid payload into several invalid shapes so all failure cases stay anchored to the same baseline request.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the baseline valid payload and invalid field values.

    Parametrize:
        scenario: Identifies which invalid signup payload shape is being exercised.
        expected_fields: The schema field names expected in the validation error output.
        Cases:
            - <id="invalid_email"> — supplies a non-email string.
            - <id="short_password"> — supplies a password shorter than the schema minimum.
            - <id="missing_client_id"> — omits the required client id field.
    """
    payload = build_auth_request_payload(faker)
    if scenario == "invalid_email":
        payload["email"] = faker.word()
    elif scenario == "short_password":
        payload["password"] = faker.password(length=7, special_chars=False)
    else:
        payload.pop("client_id")

    with pytest.raises(ValidationError, match="validation error") as exc_info:
        SignupRequest(**payload)

    error_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert expected_fields <= error_fields, (
        f"Expected validation errors for {expected_fields}, got {error_fields}"
    )


@pytest.mark.unit
def test_refresh_request_requires_long_enough_token(faker) -> None:
    """
    Purpose:
        Verifies that `app.schemas.auth.RefreshRequest` rejects a refresh token that is shorter than the schema requires.
        This matters because malformed token payloads should fail schema validation before auth service logic runs.

    Covers:
        - `app.schemas.auth.RefreshRequest`

    Rationale:
        The test uses the shortest failing token value to isolate the schema-length constraint.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the token and client id inputs.
    """
    with pytest.raises(ValidationError, match="validation error") as exc_info:
        RefreshRequest(
            refresh_token=faker.pystr(min_chars=7, max_chars=7),
            client_id=faker.uuid4(),
        )

    error_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert {"refresh_token"} <= error_fields, (
        f"Expected refresh_token validation error, got {error_fields}"
    )


@pytest.mark.unit
def test_token_pair_defaults_token_type_to_bearer(faker) -> None:
    """
    Purpose:
        Verifies that `app.schemas.auth.TokenPair` defaults `token_type` to `bearer`.
        This matters because callers rely on the response model to emit the expected auth scheme without setting it manually.

    Covers:
        - `app.schemas.auth.TokenPair`

    Rationale:
        The test omits only the token type so the defaulting behavior is the sole thing being exercised.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate token strings.
    """
    token_pair = TokenPair(
        access_token=faker.sha256(raw_output=False),
        refresh_token=faker.sha256(raw_output=False),
    )

    assert token_pair.token_type == "bearer", (
        f"Expected default token_type 'bearer', got '{token_pair.token_type}'"
    )


@pytest.mark.unit
def test_signup_response_wraps_vendor_out(faker) -> None:
    """
    Purpose:
        Verifies that `app.schemas.auth.SignupResponse` wraps a `VendorOut` instance under the `vendor` field.
        This matters because the signup API response contract exposes the created vendor through this envelope.

    Covers:
        - `app.schemas.auth.VendorOut`
        - `app.schemas.auth.SignupResponse`

    Rationale:
        The response schema is exercised directly because the contract under test is pure model composition.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate vendor field values.
    """
    vendor = VendorOut(id=faker.uuid4(), email=faker.email())
    response = SignupResponse(vendor=vendor)

    assert response.vendor == vendor, (
        f"Expected SignupResponse to wrap {vendor}, got {response.vendor}"
    )
