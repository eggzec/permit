"""
Integration tests for exception handlers.

Verifies that every handler produces responses that conform
to the error contract: correct HTTP status codes, error codes,
message round-tripping, details structure, request-id
presence/format, and uniqueness.
"""

import re

import pytest
from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exception_handlers import (
    api_exception_handler,
    build_error_details,
    general_exception_handler,
    validation_exception_handler,
)
from app.core.exceptions import (
    APIException,
    AuthenticationException,
    AuthExpiredException,
    AuthorizationException,
    BusinessLogicException,
    ConflictException,
    LicenseExpiredException,
    LicenseNotFoundException,
    LicenseRevokedException,
    NotFoundException,
    ServiceUnavailableException,
    ValidationException,
)
from app.schemas.response import ErrorDetail


# Pre-compiled UUID v4 pattern reused across request-id assertions
_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@pytest.mark.unit
def test_build_error_details_none_returns_empty_list():
    """
    Verifies that `app.core.exception_handlers._build_error_details` returns an
    empty list when given `None`. This matters because error handlers normalize
    optional detail payloads into a consistent response shape.

    Covers:
        - `app.core.exception_handlers._build_error_details`

    Rationale:
        This is a direct helper-unit test with no fixtures because the normalization rule is pure and deterministic.

    Fixtures:
        None.
    """
    details = build_error_details(None)
    assert details == [], "Expected no details when input is None"


@pytest.mark.unit
def test_build_error_details_accepts_error_detail_instance():
    """
    Verifies that `app.core.exception_handlers._build_error_details` preserves
    an existing `ErrorDetail` instance. This matters because handlers should
    not mutate already-normalized detail objects.

    Covers:
        - `app.core.exception_handlers._build_error_details`

    Rationale:
        The test uses a real `ErrorDetail` instance because the helper contract is about normalization, not copying.

    Fixtures:
        None.
    """
    item = ErrorDetail(field="email", message="Invalid email")

    details = build_error_details(item)
    assert len(details) == 1, "Expected exactly one normalized detail entry"
    assert details[0] is item, (
        "Expected ErrorDetail instance input to be preserved without copying"
    )


@pytest.mark.unit
def test_build_error_details_dict_uses_fallback_message_when_missing():
    """
    Verifies that `app.core.exception_handlers._build_error_details` supplies
    the fallback message when a detail dict omits `message`. This matters
    because API error details must always carry a message field after
    normalization.

    Covers:
        - `app.core.exception_handlers._build_error_details`

    Rationale:
        A single dict input is enough because the contract under test is the fallback message behavior.

    Fixtures:
        None.
    """
    details = build_error_details({"field": "password"})
    assert len(details) == 1, "Expected exactly one normalized detail entry"
    assert details[0].field == "password", (
        "Expected dict field to be mapped to ErrorDetail.field"
    )
    assert details[0].message == "Unknown error", (
        "Expected missing/empty dict message to use 'Unknown error' fallback"
    )


@pytest.mark.unit
def test_build_error_details_non_dict_item_is_stringified():
    """
    Verifies that `app.core.exception_handlers._build_error_details` stringifies
    non-dict inputs into a detail message. This matters because handlers may
    receive arbitrary exception detail items that still need to be serialized
    into the response contract.

    Covers:
        - `app.core.exception_handlers._build_error_details`

    Rationale:
        The runtime-error input documents the behavior for non-dict, non-`ErrorDetail` detail items.

    Fixtures:
        None.
    """
    details = build_error_details(RuntimeError("boom"))
    assert len(details) == 1, "Expected exactly one normalized detail entry"
    assert details[0].field is None, (
        "Expected non-dict inputs to map to ErrorDetail with field=None"
    )
    assert details[0].message == "boom", (
        "Expected non-dict inputs to be stringified into detail message"
    )


@pytest.fixture(scope="module")
def error_contract_app():
    """
    Provides a FastAPI app wired with the project exception handlers and test-only endpoints that trigger each handler path.

    Scope: module — the app wiring is expensive enough to share within the module and tests do not mutate the router structure.

    Provides:
        A `FastAPI` instance configured with API, validation, and general exception handlers plus endpoints that raise representative exceptions.

    Dependencies:
        None.

    Teardown:
        None.

    Note:
        The fixture exists solely to exercise the real response envelope produced by the installed handlers.
    """
    app = FastAPI()

    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    app.add_exception_handler(Exception, general_exception_handler)

    @app.get("/auth-invalid")
    async def auth_invalid():
        raise AuthenticationException("Invalid credentials")

    @app.get("/auth-expired")
    async def auth_expired():
        raise AuthExpiredException("Token has expired")

    @app.get("/forbidden")
    async def forbidden():
        raise AuthorizationException("Access denied")

    @app.get("/not-found")
    async def not_found():
        raise NotFoundException("Resource not found")

    @app.get("/conflict")
    async def conflict():
        raise ConflictException("Resource conflict")

    @app.get("/validation")
    async def validation():
        raise ValidationException(
            message="Validation failed",
            details=[
                {"field": "email", "message": "Invalid email format"},
                {"field": "password", "message": "Too short"},
            ],
        )

    @app.get("/business-logic")
    async def business_logic():
        raise BusinessLogicException(
            message="Cannot process request",
            details=[{"field": "billing", "message": "Insufficient credits"}],
        )

    @app.get("/service-unavailable")
    async def service_unavailable():
        raise ServiceUnavailableException("Database is down")

    @app.get("/license-not-found")
    async def license_not_found():
        raise LicenseNotFoundException("No active license")

    @app.get("/license-revoked")
    async def license_revoked():
        raise LicenseRevokedException("License was revoked")

    @app.get("/license-expired")
    async def license_expired():
        raise LicenseExpiredException("License has expired")

    @app.get("/general-error")
    async def general_error():
        raise RuntimeError("Unexpected error")

    class SampleRequest(BaseModel):
        name: str
        email: str

    @app.post("/validate-body")
    async def validate_body(data: SampleRequest):
        return {"status": "ok"}

    class AddressBody(BaseModel):
        street: str

    class NestedBodyRequest(BaseModel):
        address: AddressBody

    @app.post("/validate-nested")
    async def validate_nested(data: NestedBodyRequest):
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# HTTP status + error code mapping
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("endpoint", "expected_code", "expected_status"),
    [
        pytest.param(
            "/validation",
            "VALIDATION_FAILED",
            # Starlette <0.48 compatibility: use getattr fallback to literal 422
            getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            id="validation_failed",
        ),
        pytest.param(
            "/auth-invalid",
            "AUTH_INVALID",
            status.HTTP_401_UNAUTHORIZED,
            id="auth_invalid",
        ),
        pytest.param(
            "/auth-expired",
            "AUTH_EXPIRED",
            status.HTTP_401_UNAUTHORIZED,
            id="auth_expired",
        ),
        pytest.param(
            "/forbidden", "FORBIDDEN", status.HTTP_403_FORBIDDEN, id="forbidden"
        ),
        pytest.param(
            "/not-found",
            "RESOURCE_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            id="resource_not_found",
        ),
        pytest.param(
            "/license-not-found",
            "LICENSE_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            id="license_not_found",
        ),
        pytest.param(
            "/conflict",
            "RESOURCE_CONFLICT",
            status.HTTP_409_CONFLICT,
            id="resource_conflict",
        ),
        pytest.param(
            "/license-revoked",
            "LICENSE_REVOKED",
            status.HTTP_409_CONFLICT,
            id="license_revoked",
        ),
        pytest.param(
            "/license-expired",
            "LICENSE_EXPIRED",
            status.HTTP_409_CONFLICT,
            id="license_expired",
        ),
        pytest.param(
            "/business-logic",
            "BUSINESS_LOGIC_ERROR",
            # Starlette <0.48 compatibility: use getattr fallback to literal 422
            getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            id="business_logic_error",
        ),
        pytest.param(
            "/service-unavailable",
            "SERVICE_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            id="service_unavailable",
        ),
        pytest.param(
            "/general-error",
            "INTERNAL_SERVER_ERROR",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            id="internal_server_error",
        ),
    ],
)
def test_error_status_code_and_code_match(
    error_contract_app, endpoint, expected_code, expected_status
):
    """
    Verifies that each registered exception path returns the expected HTTP
    status code and error code pair. This matters because clients and
    observability tooling depend on the wire status and structured error code
    staying aligned.

    Covers:
        - `app.core.exception_handlers.api_exception_handler`
        - `app.core.exception_handlers.general_exception_handler`
        - `app.core.exception_handlers.validation_exception_handler`

    Rationale:
        The test drives the app through real endpoints because the contract under test is the final HTTP response envelope for each handler path.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.

    Parametrize:
        endpoint: The route that triggers the handler under test.
        expected_code: The error code expected in the response body.
        expected_status: The HTTP status expected on the response.
        Cases:
            - <id="validation_failed"> — validation exception path.
            - <id="auth_invalid"> — invalid-authentication path.
            - <id="auth_expired"> — expired-authentication path.
            - <id="forbidden"> — authorization failure path.
            - <id="resource_not_found"> — generic not-found path.
            - <id="license_not_found"> — license-not-found path.
            - <id="resource_conflict"> — generic conflict path.
            - <id="license_revoked"> — license-revoked path.
            - <id="license_expired"> — license-expired path.
            - <id="business_logic_error"> — business-logic error path.
            - <id="service_unavailable"> — service-unavailable path.
            - <id="internal_server_error"> — uncaught exception path.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get(endpoint)

    assert response.status_code == expected_status, (
        f"Expected HTTP status {expected_status} for {endpoint}, "
        f"got {response.status_code}: {response.text}"
    )
    error = response.json()["error"]
    assert error["code"] == expected_code, (
        f"Expected error code '{expected_code}' for "
        f"{endpoint}, got '{error['code']}'"
    )
    assert error["http_status"] == expected_status, (
        f"Expected error http_status {expected_status},"
        f" got {error['http_status']}"
    )
    # Wire vs body contract: status must match
    assert response.status_code == error["http_status"], (
        f"Response status code {response.status_code} does not match "
        f"error http_status {error['http_status']}"
    )


# ---------------------------------------------------------------------------
# Error details structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_error_details_structure(error_contract_app):
    """
    Verifies that validation-style details are serialized with the expected
    field and message pairs. This matters because API clients rely on the
    `details` list to display precise validation feedback.

    Covers:
        - `app.core.exception_handlers.api_exception_handler`

    Rationale:
        The test exercises the real `/validation` endpoint so the final response envelope is asserted end to end.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get("/validation")

    error = response.json()["error"]
    assert "details" in error, (
        f"Expected 'details' field in error response, got keys: {error.keys()}"
    )
    assert len(error["details"]) == 2, (
        f"Expected 2 detail entries, got "
        f"{len(error['details'])}: {error['details']}"
    )

    detail1 = error["details"][0]
    assert detail1["field"] == "email", (
        f"Expected first detail field 'email', got '{detail1['field']}'"
    )
    assert detail1["message"] == "Invalid email format", (
        f"Expected first detail message 'Invalid email format', "
        f"got '{detail1['message']}'"
    )

    detail2 = error["details"][1]
    assert detail2["field"] == "password", (
        f"Expected second detail field 'password', got '{detail2['field']}'"
    )
    assert detail2["message"] == "Too short", (
        "Expected second detail message 'Too short',"
        f" got '{detail2['message']}'"
    )


@pytest.mark.integration
def test_error_details_default_empty(error_contract_app):
    """
    Verifies that exception responses without explicit details still serialize
    `details` as an empty list. This matters because the API error contract
    should stay shape-stable even when no field-level detail exists.

    Covers:
        - `app.core.exception_handlers.api_exception_handler`

    Rationale:
        The test uses a real auth error endpoint because the observable response shape is the contract that matters.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get("/auth-invalid")

    error = response.json()["error"]
    assert "details" in error, (
        f"Expected 'details' field in error response, got keys: {error.keys()}"
    )
    assert error["details"] == [], (
        "Expected empty details list for exception"
        f" without details, got {error['details']}"
    )


# ---------------------------------------------------------------------------
# Validation handler field path
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validation_handler_nested_field_path(error_contract_app):
    """
    Verifies that `app.core.exception_handlers.validation_exception_handler`
    joins nested validation locations with dots. This matters because clients
    need a stable field path such as `address.street` to map nested validation
    errors back to inputs.

    Covers:
        - `app.core.exception_handlers.validation_exception_handler`

    Rationale:
        The nested-body endpoint is exercised through `TestClient` because the contract under test is the emitted validation detail field path.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.post("/validate-nested", json={"address": {}})

    assert response.status_code == getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    ), (
        "Expected status 422 for nested validation"
        f" error, got {response.status_code}"
    )
    details = response.json()["error"]["details"]
    fields = [d["field"] for d in details]
    assert "address.street" in fields, (
        f"Expected 'address.street' in validation detail fields, got {fields}"
    )


@pytest.mark.integration
def test_validation_handler_body_level_error_sets_field_to_none(
    error_contract_app,
):
    """
    Verifies that `app.core.exception_handlers.validation_exception_handler`
    emits `field=None` for body-level validation failures. This matters because
    some request errors apply to the whole body rather than a named field.

    Covers:
        - `app.core.exception_handlers.validation_exception_handler`

    Rationale:
        The test posts a scalar to an object endpoint so the handler receives a body-level location and must normalize it into a `None` field.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.post("/validate-body", json=5)

    assert response.status_code == getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    ), (
        "Expected status 422 for body-level"
        f" validation error, got {response.status_code}"
    )
    details = response.json()["error"]["details"]
    assert len(details) > 0, (
        "Expected at least one validation detail, got empty list"
    )
    # At least one detail must have field=None from the body-level loc
    assert any(d["field"] is None for d in details), (
        "Expected at least one detail with"
        f" field=None for body-level error, got {details}"
    )


# ---------------------------------------------------------------------------
# Request-id tracking
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("endpoint", "method", "json_body", "raise_exceptions"),
    [
        pytest.param(
            "/auth-invalid", "get", None, True, id="api_exception_handler"
        ),
        pytest.param(
            "/validate-body",
            "post",
            {"invalid": "data"},
            True,
            id="validation_exception_handler",
        ),
        pytest.param(
            "/general-error", "get", None, False, id="general_exception_handler"
        ),
    ],
)
def test_request_id_header_matches_body_and_is_uuid_v4(
    error_contract_app, endpoint, method, json_body, raise_exceptions
):
    """
    Verifies that every exception-handler response echoes the same request id in
    the header and body and that the value is UUIDv4-shaped. This matters
    because traceability depends on a single correlation id surviving across
    both response surfaces.

    Covers:
        - `app.core.exception_handlers.api_exception_handler`
        - `app.core.exception_handlers.general_exception_handler`
        - `app.core.exception_handlers.validation_exception_handler`

    Rationale:
        The parametrized endpoints cover one path for each handler family so the request-id contract is checked across the full error stack.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.

    Parametrize:
        endpoint: Route that triggers the handler under test.
        method: HTTP verb used to reach that route.
        json_body: Optional request JSON body for the route.
        raise_exceptions: Whether the `TestClient` should re-raise server exceptions.
        Cases:
            - <id="api_exception_handler"> — exercises an APIException-derived handler path.
            - <id="validation_exception_handler"> — exercises a request-validation handler path.
            - <id="general_exception_handler"> — exercises the uncaught-exception handler path.
    """
    client = TestClient(
        error_contract_app, raise_server_exceptions=raise_exceptions
    )
    request_method = getattr(client, method)
    kwargs = {"json": json_body} if json_body is not None else {}
    response = request_method(endpoint, **kwargs)

    assert "X-Request-ID" in response.headers, (
        "Expected 'X-Request-ID' header, got"
        f" headers: {list(response.headers.keys())}"
    )
    request_id = response.headers["X-Request-ID"]
    assert request_id, "X-Request-ID header must not be empty"

    error = response.json()["error"]
    assert request_id == error["request_id"], (
        f"Header X-Request-ID '{request_id}' does not"
        f" match body request_id '{error['request_id']}'"
    )
    assert _UUID_V4_RE.match(request_id), (
        f"request_id '{request_id}' is not a valid UUID v4 format"
    )


@pytest.mark.integration
def test_request_id_uniqueness_across_requests(error_contract_app):
    """
    Verifies that separate error responses receive distinct request ids across
    repeated requests. This matters because a reused request id would break
    per-request tracing and log correlation.

    Covers:
        - request-id generation behavior exercised through the exception handlers

    Rationale:
        Repeating the same failing request keeps the route constant while checking the per-request uniqueness contract.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)

    ids = {
        client.get("/auth-invalid").json()["error"]["request_id"]
        for _ in range(5)
    }
    assert len(ids) == 5, (
        "Expected 5 unique request_ids from 5 requests,"
        f" got {len(ids)} unique IDs."
        " request_id may not be regenerated per request."
    )


# ---------------------------------------------------------------------------
# Individual handler contracts
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_general_exception_handler_returns_sanitized_500(error_contract_app):
    """
    Verifies that `app.core.exception_handlers.general_exception_handler`
    returns a sanitized 500 response instead of leaking internal exception
    details. This matters because unexpected server errors should preserve the
    API contract without exposing internals to clients.

    Covers:
        - `app.core.exception_handlers.general_exception_handler`

    Rationale:
        The test triggers a real runtime error endpoint so the final error envelope is asserted exactly as a client would observe it.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get("/general-error")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, (
        f"Expected status 500 for general exception, got {response.status_code}"
    )
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_SERVER_ERROR", (
        f"Expected code 'INTERNAL_SERVER_ERROR', got '{error['code']}'"
    )
    assert error["http_status"] == status.HTTP_500_INTERNAL_SERVER_ERROR, (
        f"Expected http_status 500, got {error['http_status']}"
    )
    assert error["message"] == "An unexpected error occurred", (
        f"Expected sanitized error message, got: {error['message']}"
    )


# ---------------------------------------------------------------------------
# Message conformance
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validation_error_message_and_details(error_contract_app):
    """
    Verifies that `app.core.exception_handlers.validation_exception_handler`
    emits the standard validation message and non-empty detail messages. This
    matters because clients depend on a stable top-level validation message and
    usable detail entries.

    Covers:
        - `app.core.exception_handlers.validation_exception_handler`

    Rationale:
        The test exercises a real validation failure so the asserted messages come from the actual response contract.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.post("/validate-body", json={"invalid": "data"})

    error = response.json()["error"]
    assert error["message"] == "Validation error", (
        f"Expected standard validation error message, got: {error['message']}"
    )
    assert len(error["details"]) > 0, (
        "Expected at least one validation detail, got empty list"
    )
    for detail in error["details"]:
        assert detail["message"], (
            "Expected non-empty message in detail, got empty string"
        )
        assert isinstance(detail["message"], str), (
            "Expected detail message to be string,"
            f" got {type(detail['message'])}"
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("endpoint", "expected_message"),
    [
        pytest.param("/auth-invalid", "Invalid credentials", id="auth_invalid"),
        pytest.param("/auth-expired", "Token has expired", id="auth_expired"),
        pytest.param("/forbidden", "Access denied", id="forbidden"),
        pytest.param(
            "/not-found", "Resource not found", id="resource_not_found"
        ),
        pytest.param("/conflict", "Resource conflict", id="resource_conflict"),
        pytest.param("/validation", "Validation failed", id="validation_error"),
        pytest.param(
            "/business-logic",
            "Cannot process request",
            id="business_logic_error",
        ),
        pytest.param(
            "/service-unavailable", "Database is down", id="service_unavailable"
        ),
        pytest.param(
            "/license-not-found", "No active license", id="license_not_found"
        ),
        pytest.param(
            "/license-revoked", "License was revoked", id="license_revoked"
        ),
        pytest.param(
            "/license-expired", "License has expired", id="license_expired"
        ),
    ],
)
def test_raised_error_messages_roundtrip_correctly(
    error_contract_app, endpoint, expected_message
):
    """
    Verifies that exception messages raised by the test endpoints appear
    unchanged in the serialized API error response where that is the intended
    contract. This matters because domain-specific error messages are part of
    the client-visible failure contract for handled exceptions.

    Covers:
        - `app.core.exception_handlers.api_exception_handler`

    Rationale:
        The test drives each endpoint through `TestClient` because the contract under test is the final response body seen by clients.

    Fixtures:
        error_contract_app: FastAPI app configured with the project exception handlers and trigger endpoints.

    Parametrize:
        endpoint: Route that raises the exception under test.
        expected_message: The message expected in the serialized error body.
        Cases:
            - <id="auth_invalid"> — invalid-authentication message.
            - <id="auth_expired"> — expired-authentication message.
            - <id="forbidden"> — authorization message.
            - <id="resource_not_found"> — generic not-found message.
            - <id="resource_conflict"> — generic conflict message.
            - <id="validation_error"> — validation exception message.
            - <id="business_logic_error"> — business-logic message.
            - <id="service_unavailable"> — service-unavailable message.
            - <id="license_not_found"> — license-not-found message.
            - <id="license_revoked"> — license-revoked message.
            - <id="license_expired"> — license-expired message.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get(endpoint)
    error = response.json()["error"]

    assert error["message"] == expected_message, (
        f"Endpoint {endpoint} returned message '{error['message']}', "
        f"expected '{expected_message}'"
    )
