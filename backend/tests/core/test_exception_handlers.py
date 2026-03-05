"""
Integration tests for exception handlers in app.core.exception_handlers.

Verifies that every handler (api_exception_handler, validation_exception_handler,
general_exception_handler) produces responses that conform to the error contract:
correct HTTP status codes, error codes, message round-tripping, details structure,
request-id presence/format, and uniqueness.
"""

import re

import pytest
from app.core.exception_handlers import (
    api_exception_handler,
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
from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Pre-compiled UUID v4 pattern reused across request-id assertions
_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@pytest.fixture(scope="module")
def error_contract_app():
    """FastAPI app for error contract handler tests (all exception handlers, one endpoint per error type)."""
    app = FastAPI()

    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
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
    "endpoint,expected_code,expected_status",
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
    """HTTP status code and error code field must match the expected values for every exception type."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get(endpoint)

    assert response.status_code == expected_status, (
        f"Expected HTTP status {expected_status} for {endpoint}, "
        f"got {response.status_code}: {response.text}"
    )
    error = response.json()["error"]
    assert error["code"] == expected_code, (
        f"Expected error code '{expected_code}' for {endpoint}, got '{error['code']}'"
    )
    assert error["http_status"] == expected_status, (
        f"Expected error http_status {expected_status}, got {error['http_status']}"
    )
    # Explicitly validate wire vs body contract: response status must match error http_status
    assert response.status_code == error["http_status"], (
        f"Response status code {response.status_code} does not match "
        f"error http_status {error['http_status']}"
    )


# ---------------------------------------------------------------------------
# Error details structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_error_details_structure(error_contract_app):
    """Details list must contain exact field+message pairs from the raised exception."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get("/validation")

    error = response.json()["error"]
    assert "details" in error, (
        f"Expected 'details' field in error response, got keys: {error.keys()}"
    )
    assert len(error["details"]) == 2, (
        f"Expected 2 detail entries, got {len(error['details'])}: {error['details']}"
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
        f"Expected second detail message 'Too short', got '{detail2['message']}'"
    )


@pytest.mark.integration
def test_error_details_default_empty(error_contract_app):
    """Exceptions raised without details must produce an empty details list in the response."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get("/auth-invalid")

    error = response.json()["error"]
    assert "details" in error, (
        f"Expected 'details' field in error response, got keys: {error.keys()}"
    )
    assert error["details"] == [], (
        f"Expected empty details list for exception without details, got {error['details']}"
    )


# ---------------------------------------------------------------------------
# Validation handler field path
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validation_handler_nested_field_path(error_contract_app):
    """validation_exception_handler must join nested loc segments with dots.

    Sending {"address": {}} triggers loc=["body", "address", "street"];
    the handler must produce field="address.street" via its dot-join logic.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.post("/validate-nested", json={"address": {}})

    assert response.status_code == getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    ), f"Expected status 422 for nested validation error, got {response.status_code}"
    details = response.json()["error"]["details"]
    fields = [d["field"] for d in details]
    assert "address.street" in fields, (
        f"Expected 'address.street' in validation detail fields, got {fields}"
    )


@pytest.mark.integration
def test_validation_handler_body_level_error_sets_field_to_none(error_contract_app):
    """When Pydantic emits a body-level error (loc has only one element after slicing),
    validation_exception_handler must produce field=None in the detail.

    Sending an integer body against an object-typed endpoint triggers
    loc=["body"], making loc[1:] empty and field_path="", so field=None.
    """
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.post("/validate-body", json=5)

    assert response.status_code == getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    ), (
        f"Expected status 422 for body-level validation error, got {response.status_code}"
    )
    details = response.json()["error"]["details"]
    assert len(details) > 0, "Expected at least one validation detail, got empty list"
    # At least one detail must have field=None from the body-level loc
    assert any(d["field"] is None for d in details), (
        f"Expected at least one detail with field=None for a body-level error, got {details}"
    )


# ---------------------------------------------------------------------------
# Request-id tracking
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "endpoint,method,json_body,raise_exceptions",
    [
        pytest.param("/auth-invalid", "get", None, True, id="api_exception_handler"),
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
    """X-Request-ID header must be present, match the body request_id, and be a valid UUID v4."""
    client = TestClient(error_contract_app, raise_server_exceptions=raise_exceptions)
    request_method = getattr(client, method)
    kwargs = {"json": json_body} if json_body is not None else {}
    response = request_method(endpoint, **kwargs)

    assert "X-Request-ID" in response.headers, (
        f"Expected 'X-Request-ID' header in response, got headers: {list(response.headers.keys())}"
    )
    request_id = response.headers["X-Request-ID"]
    assert request_id, "X-Request-ID header must not be empty"

    error = response.json()["error"]
    assert request_id == error["request_id"], (
        f"Header X-Request-ID '{request_id}' does not match body request_id '{error['request_id']}'"
    )
    assert _UUID_V4_RE.match(request_id), (
        f"request_id '{request_id}' is not a valid UUID v4 format"
    )


@pytest.mark.integration
def test_request_id_uniqueness_across_requests(error_contract_app):
    """Repeated requests to the same endpoint must each receive a distinct request_id."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)

    ids = {client.get("/auth-invalid").json()["error"]["request_id"] for _ in range(5)}
    assert len(ids) == 5, (
        f"Expected 5 unique request_ids from 5 requests to the same endpoint, "
        f"got {len(ids)} unique IDs. request_id may not be regenerated per request."
    )


# ---------------------------------------------------------------------------
# Individual handler contracts
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_api_exception_handler_returns_correct_structure(error_contract_app):
    """api_exception_handler must return all required top-level error fields."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get("/auth-invalid")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED, (
        f"Expected status 401 for APIException, got {response.status_code}"
    )
    error = response.json()["error"]
    for field in ("code", "message", "http_status", "details", "request_id"):
        assert field in error, (
            f"Missing field '{field}' in error response, got: {error.keys()}"
        )


@pytest.mark.integration
def test_validation_exception_handler_returns_correct_structure(error_contract_app):
    """validation_exception_handler must return VALIDATION_FAILED with populated details."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.post("/validate-body", json={"invalid": "data"})

    assert response.status_code == getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    ), f"Expected status 422 for validation error, got {response.status_code}"
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED", (
        f"Expected code 'VALIDATION_FAILED', got '{error['code']}'"
    )
    assert error["http_status"] == getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    ), f"Expected http_status 422, got {error['http_status']}"
    assert len(error["details"]) > 0, (
        "Expected at least one validation detail, got empty list"
    )

    for detail in error["details"]:
        assert "field" in detail, (
            f"Expected 'field' key in detail, got keys: {detail.keys()}"
        )
        assert "message" in detail, (
            f"Expected 'message' key in detail, got keys: {detail.keys()}"
        )
        assert isinstance(detail["message"], str), (
            f"Expected detail message to be string, got {type(detail['message'])}"
        )


@pytest.mark.integration
def test_general_exception_handler_returns_sanitized_500(error_contract_app):
    """general_exception_handler must return 500 with a sanitized message, never internal details."""
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
    """validation_exception_handler must return the standard message with non-empty detail messages."""
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
            f"Expected detail message to be string, got {type(detail['message'])}"
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "endpoint,expected_message",
    [
        pytest.param("/auth-invalid", "Invalid credentials", id="auth_invalid"),
        pytest.param("/auth-expired", "Token has expired", id="auth_expired"),
        pytest.param("/forbidden", "Access denied", id="forbidden"),
        pytest.param("/not-found", "Resource not found", id="resource_not_found"),
        pytest.param("/conflict", "Resource conflict", id="resource_conflict"),
        pytest.param("/validation", "Validation failed", id="validation_error"),
        pytest.param(
            "/business-logic", "Cannot process request", id="business_logic_error"
        ),
        pytest.param(
            "/service-unavailable", "Database is down", id="service_unavailable"
        ),
        pytest.param("/license-not-found", "No active license", id="license_not_found"),
        pytest.param("/license-revoked", "License was revoked", id="license_revoked"),
        pytest.param("/license-expired", "License has expired", id="license_expired"),
    ],
)
def test_raised_error_messages_roundtrip_correctly(
    error_contract_app, endpoint, expected_message
):
    """The exact message passed to the exception constructor must appear in the response."""
    client = TestClient(error_contract_app, raise_server_exceptions=False)
    response = client.get(endpoint)
    error = response.json()["error"]

    assert error["message"] == expected_message, (
        f"Endpoint {endpoint} returned message '{error['message']}', "
        f"expected '{expected_message}'"
    )
