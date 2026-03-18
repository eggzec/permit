from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import create_access_token
from app.main import app


API_V1 = "/api/v1"


def build_auth_payload(faker, **overrides: str) -> dict[str, str]:
    """
    Builds an auth request payload with Faker-generated credentials and client
    identity.

    Used by:
        test_signup_creates_vendor_201 - creates a valid signup request body.
        test_signup_duplicate_email_returns_409 - reuses the same signup payload to trigger a duplicate conflict.
        test_signup_validation_errors_return_422 - mutates a valid payload into invalid auth-route cases.
        test_login_returns_token_pair - provisions a vendor before exercising the login route.
        test_login_rejects_invalid_credentials - produces the baseline valid credentials before one field is varied.
        test_refresh_issues_new_tokens - provisions a loginable vendor before exercising refresh.
        test_refresh_rejects_invalid_tokens - supplies the shared client id used by refresh route requests.
        test_valid_token_returns_vendor_id - creates the vendor used to access the protected test route.

    Args:
        faker: `Faker` session fixture used to generate realistic auth inputs.
        overrides: `str` keyword replacements for specific payload fields.

    Returns:
        dict[str, str]: A JSON-serializable auth payload containing `email`,
                        `password`, and `client_id`.
    """
    payload = {
        "email": faker.email(),
        "password": faker.password(length=16, special_chars=True),
        "client_id": faker.uuid4(),
    }
    payload.update(overrides)
    return payload


def signup(client: TestClient, payload: dict[str, str]):
    """
    Sends a signup request to the auth route.

    Used by:
        test_signup_creates_vendor_201 - exercises the happy-path signup contract.
        test_signup_duplicate_email_returns_409 - performs the first and second signup attempts.
        test_login_returns_token_pair - provisions a vendor before login.
        test_login_rejects_invalid_credentials - creates the baseline vendor record.
        test_refresh_issues_new_tokens - creates the vendor whose refresh token is later exchanged.
        test_refresh_rejects_invalid_tokens - creates a vendor when the invalid-token scenario still requires existing state.
        test_valid_token_returns_vendor_id - provisions the vendor used for the protected endpoint call.

    Args:
        client: `TestClient` bound to the FastAPI application under test.
        payload: `dict[str, str]` request body for the signup route.

    Returns:
        Response: The raw FastAPI test-client response from `POST /api/v1/auth/signup`.
    """
    return client.post(f"{API_V1}/auth/signup", json=payload)


def login(client: TestClient, payload: dict[str, str]):
    """
    Sends a login request to the auth route.

    Used by:
        test_login_returns_token_pair - exercises the happy-path login contract.
        test_login_rejects_invalid_credentials - submits invalid credentials against the real route.
        test_refresh_issues_new_tokens - obtains the refresh token used for the follow-up refresh call.
        test_valid_token_returns_vendor_id - obtains the access token used for the protected endpoint call.

    Args:
        client: `TestClient` bound to the FastAPI application under test.
        payload: `dict[str, str]` request body for the login route.

    Returns:
        Response: The raw FastAPI test-client response from `POST /api/v1/auth/login`.
    """
    return client.post(f"{API_V1}/auth/login", json=payload)


@pytest.mark.integration
@pytest.mark.api
def test_signup_creates_vendor_201(faker) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.signup_route` creates a vendor and
        returns the created vendor payload when the request is valid. This
        matters because the public auth API must expose the persisted vendor
        identity after a successful signup.

    Covers:
        - `app.api.routes.auth.signup_route`
        - the success path through `app.services.auth.signup`

    Rationale:
        This is a straightforward integration test that exercises the real route
        through `TestClient` without patching internal auth logic.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate a unique email,
               password, and client id.
    """
    payload = build_auth_payload(faker)
    with TestClient(app) as client:
        response = signup(client, payload)

    assert response.status_code == 201, (
        f"Expected signup status 201, got {response.status_code}: {response.json()}"
    )
    body = response.json()
    assert "data" in body, f"Expected signup response data, got {body}"
    assert body["data"]["vendor"]["email"] == payload["email"], (
        "Expected signup response email to match the submitted email"
    )
    assert "id" in body["data"]["vendor"], (
        f"Expected created vendor id in response, got {body['data']['vendor']}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_signup_duplicate_email_returns_409(faker) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.signup_route` rejects a second signup
        attempt for the same email with a conflict response. This matters
        because duplicate vendor creation must fail at the API boundary rather
        than silently creating competing accounts.

    Covers:
        - `app.api.routes.auth.signup_route`
        - duplicate-email handling in `app.services.auth.signup`

    Rationale:
        This test uses two real route calls because the duplicate-email rule is
        part of the observable API contract.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate a unique auth
               payload.
    """
    payload = build_auth_payload(faker)
    with TestClient(app) as client:
        first_response = signup(client, payload)
        second_response = signup(client, payload)

    assert first_response.status_code == 201, (
        f"Expected initial signup status 201, got {first_response.status_code}:"
        f" {first_response.json()}"
    )
    assert second_response.status_code == 409, (
        f"Expected duplicate signup status 409, got"
        f"{second_response.status_code}: {second_response.json()}"
    )


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("weak_password", id="weak_password"),
        pytest.param("missing_client_id", id="missing_client_id"),
    ],
)
def test_signup_validation_errors_return_422(faker, scenario: str) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.signup_route` returns request-validation
        errors for malformed signup payloads before service logic runs. This
        matters because the route contract must reject invalid client input
        consistently.

    Covers:
        - `app.api.routes.auth.signup_route`
        - FastAPI/Pydantic validation on `app.schemas.auth.SignupRequest`

    Rationale:
        The test mutates one valid payload into multiple invalid scenarios so
        the failure cases stay aligned with the same contract boundary.

    Fixtures:
        faker: Session-scoped `Faker` instance used to create and then vary the
               request payload.

    Parametrize:
        scenario: Names the invalid request shape being submitted.
        Cases:
            - <id="weak_password"> — password is shorter than the signup policy permits.
            - <id="missing_client_id"> — the required client id field is omitted.
    """
    payload = build_auth_payload(faker)
    if scenario == "weak_password":
        payload["password"] = faker.password(length=7, special_chars=False)
    else:
        payload.pop("client_id")

    with TestClient(app) as client:
        response = signup(client, payload)

    assert response.status_code == 422, (
        f"Expected signup validation status 422 for {scenario}, got "
        f"{response.status_code}: {response.json()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_login_returns_token_pair(faker) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.login_route` returns an access token, a
        refresh token, and the expected bearer token type for valid credentials.
        This matters because clients depend on the login route to establish an
        authenticated session.

    Covers:
        - `app.api.routes.auth.login_route`
        - the success path through `app.services.auth.login`

    Rationale:
        The test provisions a real vendor through signup first so login is
        exercised against persisted state instead of mocked collaborators.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate loginable
               credentials.
    """
    payload = build_auth_payload(faker)
    with TestClient(app) as client:
        signup(client, payload)
        response = login(client, payload)

    assert response.status_code == 200, (
        f"Expected login status 200, got {response.status_code}: "
        f"{response.json()}"
    )
    data = response.json()["data"]
    assert data["access_token"], (
        "Expected login response to include an access token"
    )
    assert data["refresh_token"], (
        "Expected login response to include a refresh token"
    )
    assert data["token_type"] == "bearer", (
        f"Expected token_type 'bearer', got '{data['token_type']}'"
    )


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.parametrize(
    "use_unknown_email,use_wrong_password",
    [
        pytest.param(True, False, id="unknown_email"),
        pytest.param(False, True, id="wrong_password"),
    ],
)
def test_login_rejects_invalid_credentials(
    faker, use_unknown_email: bool, use_wrong_password: bool
) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.login_route` rejects unknown-email and
        wrong-password submissions with the same unauthorized response. This
        matters because the route must not authenticate invalid credentials
        regardless of which field is wrong.

    Covers:
        - `app.api.routes.auth.login_route`
        - invalid-credential handling in `app.services.auth.login`

    Rationale:
        The test keeps one provisioned vendor and varies only one credential
        dimension per case so the failure reason stays isolated.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate valid and
               alternate credentials.

    Parametrize:
        use_unknown_email: Whether the login attempt swaps in an unrecognized email address.
        use_wrong_password: Whether the login attempt swaps in an incorrect password.
        Cases:
            - <id="unknown_email"> — submits an email that was never signed up.
            - <id="wrong_password"> — submits the persisted email with the wrong password.
    """
    payload = build_auth_payload(faker)
    invalid_payload = dict(payload)
    invalid_payload["email"] = (
        faker.email() if use_unknown_email else payload["email"]
    )
    invalid_payload["password"] = (
        faker.password(length=16, special_chars=True)
        if use_wrong_password
        else payload["password"]
    )

    with TestClient(app) as client:
        signup(client, payload)
        response = login(client, invalid_payload)

    assert response.status_code == 401, (
        f"Expected login rejection status 401, got {response.status_code}: "
        f"{response.json()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_refresh_issues_new_tokens(faker) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.refresh_route` exchanges a valid refresh
        token for a new token pair. This matters because authenticated clients
        rely on refresh to continue operating without re-entering credentials.

    Covers:
        - `app.api.routes.auth.refresh_route`
        - the success path through `app.services.auth.refresh`

    Rationale:
        The test drives the full signup-to-login-to-refresh route sequence
        because the refresh contract depends on real issued tokens.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the signup/login
               payload and client id.
    """
    payload = build_auth_payload(faker)
    with TestClient(app) as client:
        signup(client, payload)
        login_response = login(client, payload)
        refresh_response = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": login_response.json()["data"]["refresh_token"],
                "client_id": payload["client_id"],
            },
        )

    assert refresh_response.status_code == 200, (
        f"Expected refresh status 200, got {refresh_response.status_code}: "
        f"{refresh_response.json()}"
    )
    data = refresh_response.json()["data"]
    assert data["access_token"], (
        "Expected refresh response to include an access token"
    )
    assert data["refresh_token"], (
        "Expected refresh response to include a refresh token"
    )


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.parametrize(
    "token_kind",
    [
        pytest.param("access_token", id="access_token"),
        pytest.param("garbage_token", id="garbage_token"),
    ],
)
def test_refresh_rejects_invalid_tokens(
    app_settings: Settings, faker, token_kind: str
) -> None:
    """
    Purpose:
        Verifies that `api.routes.auth.refresh_route` rejects invalid
        refresh-token inputs such as access tokens and garbage strings. This
        matters because the refresh endpoint must enforce token-type and
        token-integrity checks at the API boundary.

    Covers:
        - `app.api.routes.auth.refresh_route`
        - invalid-token handling in `app.services.auth.refresh`

    Rationale:
        Real tokens are generated through the project security helpers so the
        test documents the external contract rather than any JWT library
        internals.

    Fixtures:
        app_settings: Shared `Settings` object containing the signing secret
                      used to mint the invalid token variants.
        faker: Session-scoped `Faker` instance used to generate payload values
               and the garbage token string.

    Parametrize:
        token_kind: Identifies which invalid token variant is submitted to the refresh route.
        Cases:
            - <id="access_token"> — uses a real access token where a refresh token is required.
            - <id="garbage_token"> — uses an unsigned arbitrary string that should fail decoding.
    """
    payload = build_auth_payload(faker)
    invalid_token = (
        create_access_token(faker.uuid4(), app_settings)
        if token_kind == "access_token"
        else faker.sha256(raw_output=False)
    )

    with TestClient(app) as client:
        if token_kind == "access_token":
            signup(client, payload)
        response = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": invalid_token,
                "client_id": payload["client_id"],
            },
        )

    assert response.status_code == 401, (
        f"Expected refresh rejection status 401 for {token_kind}, got "
        f"{response.status_code}: {response.json()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_missing_token_returns_401() -> None:
    """
    Purpose:
        Verifies that the protected test route rejects unauthenticated requests
        with a 401 response. This matters because the route exists to prove the
        authentication dependency protects downstream handlers.

    Covers:
        - the protected route registered in `backend/tests/conftest.py`
        - `app.api.deps.get_current_vendor_id`

    Rationale:
        This test is intentionally minimal because the contract under test is
        the authentication gate itself, not the route payload.

    Fixtures:
        None.
    """
    with TestClient(app) as client:
        response = client.get("/tests/protected-test")

    assert response.status_code == 401, (
        f"Expected protected route status 401 without token, got "
        f"{response.status_code}: {response.json()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_expired_token_returns_401(app_settings: Settings, faker) -> None:
    """
    Purpose:
        Verifies that the protected route rejects an expired access token.
        This matters because stale tokens must fail before the protected handler
        executes any application logic.

    Covers:
        - the protected route registered in `backend/tests/conftest.py`
        - token-expiry enforcement in `app.api.deps.get_current_vendor_id`

    Rationale:
        The test uses a real signed token with a negative expiry delta so it
        exercises the same path production requests use.

    Fixtures:
        app_settings: Shared `Settings` object used to sign the expired access token.
        faker: Session-scoped `Faker` instance used to generate the vendor id claim.
    """
    token = create_access_token(
        faker.uuid4(), app_settings, expires_delta=timedelta(seconds=-1)
    )
    with TestClient(app) as client:
        response = client.get(
            "/tests/protected-test",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401, (
        f"Expected expired token status 401, got {response.status_code}: {response.json()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_valid_token_returns_vendor_id(faker) -> None:
    """
    Purpose:
        Verifies that a valid access token reaches the protected route and that
        both the dependency output and database session context contain the
        created vendor id. This matters because the authenticated API and the
        RLS database context must stay aligned for tenant isolation to work.

    Covers:
        - the protected route registered in `backend/tests/conftest.py`
        - `app.api.deps.get_current_vendor_id`
        - `app.api.deps.get_rls_cursor`

    Rationale:
        The test performs the full signup and login flow so the protected-route
        assertion is made against a real issued token and real database context.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the auth payload
    """
    payload = build_auth_payload(faker)
    with TestClient(app) as client:
        signup_response = signup(client, payload)
        created_vendor_id = signup_response.json()["data"]["vendor"]["id"]
        login_response = login(client, payload)
        access_token = login_response.json()["data"]["access_token"]
        protected_response = client.get(
            "/tests/protected-test",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert login_response.status_code == 200, (
        f"Expected login status 200 before protected call, got "
        f"{login_response.status_code}: {login_response.json()}"
    )
    assert protected_response.status_code == 200, (
        f"Expected protected route status 200, got "
        f"{protected_response.status_code}: {protected_response.json()}"
    )
    body = protected_response.json()
    assert body["vendor_id"] == created_vendor_id, (
        f"Expected route vendor_id '{created_vendor_id}', got "
        f"'{body['vendor_id']}'"
    )
    assert body["db_vendor_id"] == created_vendor_id, (
        f"Expected RLS vendor_id '{created_vendor_id}', got "
        f"'{body['db_vendor_id']}'"
    )
