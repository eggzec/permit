from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api import deps
from app.core.exceptions import (
    AuthenticationException,
    ServiceUnavailableException,
)
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    create_refresh_token,
)


def build_fake_cursor() -> SimpleNamespace:
    """
    Builds a cursor-like object that records executed SQL statements and parameters.

    Used by:
        test_get_db_yields_cursor_when_pool_exists - asserts that the yielded cursor object is the same cursor provided by the fake pool.
        test_get_rls_cursor_sets_context_and_yields_cursor - captures the RLS context statement executed before the cursor is yielded.

    Args:
        None.

    Returns:
        SimpleNamespace: A cursor substitute with `executed` and `execute` attributes.
    """
    cursor = SimpleNamespace(executed=[])

    def execute(statement: str, params=None) -> None:
        cursor.executed.append((statement, params))

    cursor.execute = execute
    return cursor


def build_fake_connection(cursor: SimpleNamespace) -> SimpleNamespace:
    """
    Builds a connection-like object that yields the provided fake cursor and counts cursor acquisitions.

    Used by:
        test_get_db_yields_cursor_when_pool_exists - asserts that one cursor is opened from the borrowed connection.
        test_get_rls_cursor_sets_context_and_yields_cursor - provides the cursor used to observe the RLS setup SQL.

    Args:
        cursor: `SimpleNamespace` cursor substitute returned by `build_fake_cursor`.

    Returns:
        SimpleNamespace: A connection substitute with `cursor_instance`, `cursor_calls`, and `cursor()` attributes.
    """
    connection = SimpleNamespace(cursor_instance=cursor, cursor_calls=0)

    @contextmanager
    def cursor_context():
        connection.cursor_calls += 1
        yield cursor

    connection.cursor = cursor_context
    return connection


def build_fake_pool(connection: SimpleNamespace) -> SimpleNamespace:
    """
    Builds a pool-like object that yields the provided fake connection and counts connection acquisitions.

    Used by:
        test_get_db_yields_cursor_when_pool_exists - asserts that one pooled connection is borrowed.
        test_get_rls_cursor_sets_context_and_yields_cursor - provides the connection whose cursor receives the RLS setup SQL.

    Args:
        connection: `SimpleNamespace` connection substitute returned by `build_fake_connection`.

    Returns:
        SimpleNamespace: A pool substitute with `connection_instance`, `connection_calls`, and `connection()` attributes.
    """
    pool = SimpleNamespace(connection_instance=connection, connection_calls=0)

    @contextmanager
    def connection_context():
        pool.connection_calls += 1
        yield connection

    pool.connection = connection_context
    return pool


def build_request(**state) -> SimpleNamespace:
    """
    Builds a request-like object whose nested `app.state` can be tailored for dependency tests.

    Used by:
        test_get_db_yields_cursor_when_pool_exists - supplies a request object with a fake pool attached.
        test_get_db_raises_when_pool_missing - supplies a request object whose pool is absent.
        test_get_settings_raises_when_settings_missing - supplies a request object whose settings are absent.
        test_get_settings_returns_settings_when_present - supplies a request object with a valid settings object attached.
        test_get_rls_cursor_raises_when_pool_missing - supplies a request object whose pool is absent.
        test_get_rls_cursor_sets_context_and_yields_cursor - supplies a request object with a fake pool attached.

    Args:
        state: Application state fields to install under `request.app.state`.

    Returns:
        SimpleNamespace: A lightweight request substitute with `app.state` attributes matching the provided keyword arguments.
    """
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))


def make_credentials(token: str) -> HTTPAuthorizationCredentials:
    """
    Wraps a raw bearer token string in FastAPI's authorization-credentials type.

    Used by:
        test_get_current_vendor_id_payload_errors - supplies credentials to the auth dependency under malformed payload cases.
        test_get_current_vendor_id_rejects_invalid_tokens - supplies credentials for invalid token variants.
        test_get_current_vendor_id_returns_vendor_id_from_valid_access_token - supplies credentials for the happy-path access token.

    Args:
        token: `str` bearer token to place into the credentials wrapper.

    Returns:
        HTTPAuthorizationCredentials: Credentials with the `Bearer` scheme and the provided token string.
    """
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def build_access_payload(
    faker, **overrides
) -> dict[str, str | datetime | None]:
    """
    Builds a signed-token payload shape for `get_current_vendor_id` tests.

    Used by:
        test_get_current_vendor_id_payload_errors - creates malformed access-token payloads without patching internal decode helpers.

    Args:
        faker: `Faker` session fixture used to generate a realistic vendor id.
        overrides: Payload field replacements applied on top of the default access-token claims.

    Returns:
        dict[str, str | datetime | None]: A token payload with `token_type`, `vendor_id`, and `exp` claims.
    """
    payload: dict[str, str | datetime | None] = {
        "token_type": "access",
        "vendor_id": faker.uuid4(),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return payload


@pytest.mark.unit
def test_get_db_yields_cursor_when_pool_exists():
    """
    Verifies that `app.api.deps.get_db` opens one pooled connection, yields one
    cursor, and then terminates cleanly. This matters because route dependencies
    rely on `get_db` to provide the database cursor used by downstream logic.

    Covers:
        - `app.api.deps.get_db`

    Rationale:
        The test uses lightweight fake pool and connection objects because the contract under test is dependency plumbing rather than SQL behavior.

    Fixtures:
        None.

    """
    cursor = build_fake_cursor()
    pool = build_fake_pool(build_fake_connection(cursor))
    request = build_request(db_pool=pool)

    generator = deps.get_db(request)
    yielded = next(generator)
    assert yielded is cursor, "get_db must yield the cursor from the pool"

    with pytest.raises(StopIteration, match=""):
        next(generator)

    assert pool.connection_calls == 1, (
        "get_db must open exactly one pooled connection"
    )
    assert pool.connection_instance.cursor_calls == 1, (
        "get_db must open exactly one cursor from the pooled connection"
    )


@pytest.mark.unit
def test_get_db_raises_when_pool_missing():
    """
    Verifies that `app.api.deps.get_db` raises a service-unavailable error when
    the application state has no database pool. This matters because route
    handlers should fail with a clear infrastructure error instead of
    dereferencing a missing pool.

    Covers:
        - `app.api.deps.get_db`

    Rationale:
        A minimal request stub is enough because the failure happens before any database connection is attempted.

    Fixtures:
        None.

    """
    request = build_request(db_pool=None)

    with pytest.raises(
        ServiceUnavailableException, match="Database pool not initialized"
    ):
        next(deps.get_db(request))


@pytest.mark.unit
def test_get_settings_raises_when_settings_missing():
    """
    Verifies that `app.api.deps.get_settings` fails fast when application
    settings are absent from `app.state`. This matters because auth and
    configuration-dependent code expects the dependency to provide a valid
    settings object.

    Covers:
        - `app.api.deps.get_settings`

    Rationale:
        The request stub contains only the missing state needed to trigger the error path.

    Fixtures:
        None.

    """
    request = build_request(settings=None)

    with pytest.raises(
        ServiceUnavailableException, match="Settings not initialized"
    ):
        deps.get_settings(request)


@pytest.mark.unit
def test_get_settings_returns_settings_when_present(app_settings):
    """
    Verifies that `app.api.deps.get_settings` returns the exact settings object
    stored on application state. This matters because callers rely on
    configuration identity and values from the dependency rather than a copied
    object.

    Covers:
        - `app.api.deps.get_settings`

    Rationale:
        The assertion uses object identity because the dependency contract is to return the existing settings instance.

    Fixtures:
        app_settings: Shared `Settings` object used to populate the request state.

    """
    request = build_request(settings=app_settings)

    resolved = deps.get_settings(request)
    assert resolved is app_settings, (
        "get_settings must return the settings object from app state"
    )


@pytest.mark.unit
def test_get_rls_cursor_raises_when_pool_missing(faker):
    """
    Verifies that `app.api.deps.get_rls_cursor` raises a service-unavailable
    error when no database pool is configured. This matters because
    authenticated routes still need the underlying pool before
    row-level-security context can be installed.

    Covers:
        - `app.api.deps.get_rls_cursor`

    Rationale:
        The test keeps the request stub minimal because the failure occurs before any context-setting SQL executes.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate a vendor id for the dependency call.

    """
    request = build_request(db_pool=None)

    with pytest.raises(
        ServiceUnavailableException, match="Database pool not initialized"
    ):
        next(deps.get_rls_cursor(request, vendor_id=faker.uuid4()))


@pytest.mark.unit
def test_get_rls_cursor_sets_context_and_yields_cursor(faker):
    """
    Verifies that `app.api.deps.get_rls_cursor` sets the authenticated vendor
    context in SQL before yielding the cursor. This matters because
    row-level-security queries depend on the app context being installed for the
    current vendor.

    Covers:
        - `app.api.deps.get_rls_cursor`

    Rationale:
        Fake cursor objects are sufficient here because the contract being verified is the exact SQL statement and yielded cursor object.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the vendor id claim.

    """
    vendor_id = faker.uuid4()
    cursor = build_fake_cursor()
    pool = build_fake_pool(build_fake_connection(cursor))
    request = build_request(db_pool=pool)

    generator = deps.get_rls_cursor(request, vendor_id=vendor_id)
    yielded = next(generator)
    assert yielded is cursor, "get_rls_cursor must yield the DB cursor"
    assert len(cursor.executed) == 1, (
        "get_rls_cursor must set app context exactly once per request"
    )
    assert cursor.executed[0] == (
        "SELECT app.set_app_context(%s)",
        (vendor_id,),
    ), "get_rls_cursor must set app context using the authenticated vendor_id"

    with pytest.raises(StopIteration, match=""):
        next(generator)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("scenario", "expected_message"),
    [
        pytest.param(
            "missing_vendor_id", "Invalid token payload", id="missing_vendor_id"
        ),
        pytest.param(
            "malformed_vendor_id",
            "Invalid token payload",
            id="malformed_vendor_id",
        ),
    ],
)
def test_get_current_vendor_id_payload_errors(
    app_settings, faker, scenario: str, expected_message: str
) -> None:
    """
    Verifies that `app.api.deps.get_current_vendor_id` rejects access tokens
    whose decoded payload omits or corrupts the vendor id claim. This matters
    because authorization depends on a valid vendor identity being present in
    every access token.

    Covers:
        - `app.api.deps.get_current_vendor_id`
        - payload validation after token decoding

    Rationale:
        The test signs real JWT payloads with malformed claims so it documents the dependency contract without patching decode helpers.

    Fixtures:
        app_settings: Shared `Settings` object containing the JWT signing secret.
        faker: Session-scoped `Faker` instance used to generate claim values.

    Parametrize:
        scenario: Identifies which vendor-id payload defect is being exercised.
        expected_message: The authentication error expected for the malformed payload.
        Cases:
            - <id="missing_vendor_id"> — the vendor id claim is present but null.
            - <id="malformed_vendor_id"> — the vendor id claim is present but not a valid UUID string.
    """
    token_payload = (
        build_access_payload(faker, vendor_id=None)
        if scenario == "missing_vendor_id"
        else build_access_payload(faker, vendor_id=faker.word())
    )
    token = jwt.encode(
        token_payload, app_settings.SECRET_KEY, algorithm=JWT_ALGORITHM
    )

    with pytest.raises(AuthenticationException, match=expected_message):
        deps.get_current_vendor_id(make_credentials(token), app_settings)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("token_factory", "expected_message"),
    [
        pytest.param(
            lambda faker, settings: create_refresh_token(
                faker.uuid4(), settings
            ),
            "Invalid token type",
            id="refresh_token",
        ),
        pytest.param(
            lambda faker, settings: create_access_token(
                faker.uuid4(), settings, expires_delta=timedelta(seconds=-1)
            ),
            "Invalid or expired token",
            id="expired_token",
        ),
        pytest.param(
            lambda faker, settings: faker.sha256(raw_output=False),
            "Invalid or expired token",
            id="garbage_token",
        ),
    ],
)
def test_get_current_vendor_id_rejects_invalid_tokens(
    app_settings, faker, token_factory, expected_message: str
) -> None:
    """
    Verifies that `app.api.deps.get_current_vendor_id` rejects non-access,
    expired, and garbage bearer tokens. This matters because authenticated
    endpoints depend on the dependency to enforce token type and expiry rules
    uniformly.

    Covers:
        - `app.api.deps.get_current_vendor_id`
        - invalid-token handling in `app.core.security.decode_token`

    Rationale:
        The token variants are produced through real project helpers and raw strings so the test stays at the contract boundary instead of asserting JWT-library internals.

    Fixtures:
        app_settings: Shared `Settings` object used to sign token variants.
        faker: Session-scoped `Faker` instance used to generate vendor ids and the garbage token string.

    Parametrize:
        token_factory: Produces the invalid token variant for the scenario.
        expected_message: The authentication error expected from the dependency.
        Cases:
            - <id="refresh_token"> — a refresh token is supplied where an access token is required.
            - <id="expired_token"> — an already-expired access token is supplied.
            - <id="garbage_token"> — an arbitrary non-token string is supplied.
    """
    token = token_factory(faker, app_settings)

    with pytest.raises(AuthenticationException, match=expected_message):
        deps.get_current_vendor_id(make_credentials(token), app_settings)


@pytest.mark.unit
def test_get_current_vendor_id_returns_vendor_id_from_valid_access_token(
    app_settings, faker
) -> None:
    """
    Verifies that `app.api.deps.get_current_vendor_id` returns the vendor id
    claim from a valid signed access token. This matters because downstream
    route code depends on receiving the authenticated vendor identity from the
    dependency.

    Covers:
        - `app.api.deps.get_current_vendor_id`

    Rationale:
        The test uses a real access token generated by the project security helper so the claim extraction path matches production behavior.

    Fixtures:
        app_settings: Shared `Settings` object used to sign the access token.
        faker: Session-scoped `Faker` instance used to generate the vendor id claim.

    """
    vendor_id = faker.uuid4()
    token = create_access_token(vendor_id, app_settings)

    resolved_vendor_id = deps.get_current_vendor_id(
        make_credentials(token), app_settings
    )
    assert resolved_vendor_id == vendor_id, (
        f"Expected authenticated vendor_id '{vendor_id}', got "
        f"'{resolved_vendor_id}'"
    )


@pytest.mark.unit
def test_get_current_vendor_id_requires_credentials(app_settings) -> None:
    """
    Verifies that `app.api.deps.get_current_vendor_id` rejects requests that do
    not include bearer credentials at all. This matters because the dependency
    is the authentication gate for protected routes.

    Covers:
        - `app.api.deps.get_current_vendor_id`

    Rationale:
        This is the simplest unauthenticated boundary case and does not require token generation.

    Fixtures:
        app_settings: Shared `Settings` object passed into the dependency call.

    """
    with pytest.raises(
        AuthenticationException, match="Missing authentication token"
    ):
        deps.get_current_vendor_id(None, app_settings)
