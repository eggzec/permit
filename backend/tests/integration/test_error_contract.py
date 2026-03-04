"""
Integration tests for error contract conformance.

Ensures that all API error responses consistently include the http_status field,
matching the actual HTTP response status code, and conform to the ErrorResponse schema.
"""

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

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
from app.core.exception_handlers import (
    api_exception_handler,
    general_exception_handler,
    validation_exception_handler,
)
from app.schemas.response import ErrorCode, ErrorResponse, ErrorBodyResponse
from fastapi.exceptions import RequestValidationError


@pytest.fixture
def app_with_handlers():
    """Create a FastAPI app with all exception handlers configured"""
    mock_app = FastAPI()

    # Register exception handlers
    mock_app.add_exception_handler(APIException, api_exception_handler)
    mock_app.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    mock_app.add_exception_handler(Exception, general_exception_handler)

    # Test endpoints that raise different exceptions
    @mock_app.get("/auth-invalid")
    async def auth_invalid():
        raise AuthenticationException("Invalid credentials")

    @mock_app.get("/auth-expired")
    async def auth_expired():
        raise AuthExpiredException("Token has expired")

    @mock_app.get("/forbidden")
    async def forbidden():
        raise AuthorizationException("Access denied")

    @mock_app.get("/not-found")
    async def not_found():
        raise NotFoundException("Resource not found")

    @mock_app.get("/conflict")
    async def conflict():
        raise ConflictException("Resource conflict")

    @mock_app.get("/validation")
    async def validation():
        raise ValidationException(
            message="Validation failed",
            details=[
                {"field": "email", "message": "Invalid email format"},
                {"field": "password", "message": "Too short"},
            ],
        )

    @mock_app.get("/business-logic")
    async def business_logic():
        raise BusinessLogicException(
            message="Cannot process request",
            details=[{"field": "billing", "message": "Insufficient credits"}],
        )

    @mock_app.get("/service-unavailable")
    async def service_unavailable():
        raise ServiceUnavailableException("Database is down")

    @mock_app.get("/license-not-found")
    async def license_not_found():
        raise LicenseNotFoundException("No active license")

    @mock_app.get("/license-revoked")
    async def license_revoked():
        raise LicenseRevokedException("License was revoked")

    @mock_app.get("/license-expired")
    async def license_expired():
        raise LicenseExpiredException("License has expired")

    @mock_app.get("/general-error")
    async def general_error():
        raise RuntimeError("Unexpected error")

    # Test endpoint for Pydantic validation
    class SampleRequest(BaseModel):
        """Sample request model for testing Pydantic validation"""
        name: str
        email: str

    @mock_app.post("/validate-body")
    async def validate_body(data: SampleRequest):
        return {"status": "ok"}

    return mock_app


@pytest.mark.integration
class TestErrorResponseStructure:
    """Test that error responses have the correct structure"""

    def test_error_response_schema_has_required_fields(self):
        """Test that ErrorBodyResponse has all required fields"""
        error_body = ErrorBodyResponse(
            code=ErrorCode.VALIDATION_FAILED,
            message="Test message",
            http_status=status.HTTP_400_BAD_REQUEST,
            details=[],
            request_id="req-123",
        )

        assert error_body.code == ErrorCode.VALIDATION_FAILED
        assert error_body.message == "Test message"
        assert error_body.http_status == status.HTTP_400_BAD_REQUEST
        assert error_body.details == []
        assert error_body.request_id == "req-123"

    def test_error_response_schema_http_status_required(self):
        """Test that http_status is a required field"""
        with pytest.raises(ValidationError):
            ErrorBodyResponse(
                code=ErrorCode.VALIDATION_FAILED,
                message="Test message",
                # Missing http_status
                request_id="req-123",
            )

    def test_error_response_schema_request_id_required(self):
        """Test that request_id is a required field"""
        with pytest.raises(ValidationError):
            ErrorBodyResponse(
                code=ErrorCode.VALIDATION_FAILED,
                message="Test message",
                http_status=status.HTTP_400_BAD_REQUEST,
                # Missing request_id
            )

    def test_error_response_envelope_structure(self):
        """Test that ErrorResponse has error field of type ErrorBodyResponse"""
        error_response = ErrorResponse(
            error=ErrorBodyResponse(
                code=ErrorCode.VALIDATION_FAILED,
                message="Test",
                http_status=status.HTTP_400_BAD_REQUEST,
                request_id="req-123",
            )
        )

        assert isinstance(error_response.error, ErrorBodyResponse)
        assert error_response.error.http_status == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestErrorCodesCatalog:
    """Test that all error codes from the catalog exist and map correctly"""

    @pytest.mark.parametrize("error_code_name", [
        pytest.param("AUTH_INVALID", id="auth_invalid"),
        pytest.param("AUTH_EXPIRED", id="auth_expired"),
        pytest.param("FORBIDDEN", id="forbidden"),
        pytest.param("RESOURCE_NOT_FOUND", id="resource_not_found"),
        pytest.param("RESOURCE_CONFLICT", id="resource_conflict"),
        pytest.param("VALIDATION_FAILED", id="validation_failed"),
        pytest.param("INTERNAL_SERVER_ERROR", id="internal_server_error"),
        pytest.param("LICENSE_NOT_FOUND", id="license_not_found"),
        pytest.param("LICENSE_REVOKED", id="license_revoked"),
        pytest.param("LICENSE_EXPIRED", id="license_expired"),
    ])
    def test_error_code_exists_and_has_correct_value(self, error_code_name):
        """Test that error code exists in catalog with correct value"""
        assert hasattr(ErrorCode, error_code_name), (
            f"ErrorCode.{error_code_name} does not exist"
        )
        error_code = getattr(ErrorCode, error_code_name)
        assert error_code.value == error_code_name, (
            f"ErrorCode.{error_code_name}.value is '{error_code.value}', "
            f"expected '{error_code_name}'"
        )


@pytest.mark.integration
class TestErrorHttpStatusMapping:
    """Test that error codes map to correct HTTP status codes"""

    @pytest.mark.parametrize("endpoint,expected_code,expected_status", [
        pytest.param("/validation", "VALIDATION_FAILED", status.HTTP_422_UNPROCESSABLE_CONTENT, id="validation_failed"),
        pytest.param("/auth-invalid", "AUTH_INVALID", status.HTTP_401_UNAUTHORIZED, id="auth_invalid"),
        pytest.param("/auth-expired", "AUTH_EXPIRED", status.HTTP_401_UNAUTHORIZED, id="auth_expired"),
        pytest.param("/forbidden", "FORBIDDEN", status.HTTP_403_FORBIDDEN, id="forbidden"),
        pytest.param("/not-found", "RESOURCE_NOT_FOUND", status.HTTP_404_NOT_FOUND, id="resource_not_found"),
        pytest.param("/license-not-found", "LICENSE_NOT_FOUND", status.HTTP_404_NOT_FOUND, id="license_not_found"),
        pytest.param("/conflict", "RESOURCE_CONFLICT", status.HTTP_409_CONFLICT, id="resource_conflict"),
        pytest.param("/license-revoked", "LICENSE_REVOKED", status.HTTP_409_CONFLICT, id="license_revoked"),
        pytest.param("/license-expired", "LICENSE_EXPIRED", status.HTTP_409_CONFLICT, id="license_expired"),
        pytest.param("/business-logic", "BUSINESS_LOGIC_ERROR", status.HTTP_422_UNPROCESSABLE_CONTENT, id="business_logic_error"),
        pytest.param("/service-unavailable", "SERVICE_UNAVAILABLE", status.HTTP_503_SERVICE_UNAVAILABLE, id="service_unavailable"),
        pytest.param("/general-error", "INTERNAL_SERVER_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR, id="internal_server_error"),
    ])
    def test_error_status_code_and_code_match(self, app_with_handlers, endpoint, expected_code, expected_status):
        """Test that error code and HTTP status code match expected values"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get(endpoint)

        assert response.status_code == expected_status
        error = response.json()["error"]
        assert error["code"] == expected_code
        assert error["http_status"] == expected_status


@pytest.mark.integration
class TestErrorDetailsStructure:
    """Test that error details are properly formatted"""

    def test_error_details_structure(self, app_with_handlers):
        """Test that error details have field and message"""
        client = TestClient(app_with_handlers)
        response = client.get("/validation")

        error = response.json()["error"]
        assert "details" in error
        assert len(error["details"]) == 2

        # Check first error detail
        detail1 = error["details"][0]
        assert "field" in detail1
        assert "message" in detail1
        assert detail1["field"] == "email"
        assert detail1["message"] == "Invalid email format"

        # Check second error detail
        detail2 = error["details"][1]
        assert detail2["field"] == "password"
        assert detail2["message"] == "Too short"

    def test_error_details_default_empty(self, app_with_handlers):
        """Test that error details default to empty list"""
        client = TestClient(app_with_handlers)
        response = client.get("/auth-invalid")

        error = response.json()["error"]
        assert "details" in error
        assert error["details"] == []


@pytest.mark.integration
class TestRequestIdTracking:
    """Test that request IDs are properly tracked and returned"""

    def test_request_id_in_response(self, app_with_handlers):
        """Test that request_id is included in error response"""
        client = TestClient(app_with_handlers)
        response = client.get("/auth-invalid")

        error = response.json()["error"]
        assert "request_id" in error
        assert error["request_id"]  # Should not be empty
        assert isinstance(error["request_id"], str)

    def test_request_id_in_header(self, app_with_handlers):
        """Test that request_id is returned in X-Request-ID header and matches body"""
        client = TestClient(app_with_handlers)
        response = client.get("/auth-invalid")

        assert "X-Request-ID" in response.headers
        assert response.headers["X-Request-ID"]
        
        # Verify header request_id matches the one in response body
        error = response.json()["error"]
        assert response.headers["X-Request-ID"] == error["request_id"]


@pytest.mark.integration
class TestErrorMessageConsistency:
    """Test that HTTP status codes match error response http_status field"""

    @pytest.mark.parametrize("endpoint,expected_status", [
        pytest.param("/auth-invalid", status.HTTP_401_UNAUTHORIZED, id="auth_invalid"),
        pytest.param("/auth-expired", status.HTTP_401_UNAUTHORIZED, id="auth_expired"),
        pytest.param("/forbidden", status.HTTP_403_FORBIDDEN, id="forbidden"),
        pytest.param("/not-found", status.HTTP_404_NOT_FOUND, id="resource_not_found"),
        pytest.param("/license-not-found", status.HTTP_404_NOT_FOUND, id="license_not_found"),
        pytest.param("/conflict", status.HTTP_409_CONFLICT, id="resource_conflict"),
        pytest.param("/license-revoked", status.HTTP_409_CONFLICT, id="license_revoked"),
        pytest.param("/license-expired", status.HTTP_409_CONFLICT, id="license_expired"),
        pytest.param("/validation", status.HTTP_422_UNPROCESSABLE_CONTENT, id="validation_error"),
        pytest.param("/business-logic", status.HTTP_422_UNPROCESSABLE_CONTENT, id="business_logic_error"),
        pytest.param("/service-unavailable", status.HTTP_503_SERVICE_UNAVAILABLE, id="service_unavailable"),
        pytest.param("/general-error", status.HTTP_500_INTERNAL_SERVER_ERROR, id="internal_server_error"),
    ])
    def test_http_status_matches_response_status(self, app_with_handlers, endpoint, expected_status):
        """Test that http_status field matches actual HTTP response status"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get(endpoint)
        error = response.json()["error"]

        assert response.status_code == expected_status, (
            f"Endpoint {endpoint} returned {response.status_code}, "
            f"expected {expected_status}"
        )
        assert error["http_status"] == expected_status, (
            f"Endpoint {endpoint} has http_status {error['http_status']}, "
            f"expected {expected_status}"
        )


@pytest.mark.integration
class TestExceptionHandlers:
    """Test individual exception handlers"""

    def test_api_exception_handler(self, app_with_handlers):
        """Test that APIException handler returns correct structure"""
        client = TestClient(app_with_handlers)
        response = client.get("/auth-invalid")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        data = response.json()

        # Verify response has error key
        assert "error" in data
        error = data["error"]

        # Verify all required fields are present
        assert "code" in error
        assert "message" in error
        assert "http_status" in error
        assert "details" in error
        assert "request_id" in error

    def test_validation_exception_handler(self, app_with_handlers):
        """Test that validation errors are handled correctly by validation_exception_handler"""
        client = TestClient(app_with_handlers)
        # POST invalid data missing required fields to trigger Pydantic validation error
        response = client.post("/validate-body", json={"invalid": "data"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        error = response.json()["error"]

        assert error["code"] == "VALIDATION_FAILED"
        assert error["http_status"] == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert len(error["details"]) > 0  # Should have validation error details

    def test_general_exception_handler(self, app_with_handlers):
        """Test that unhandled exceptions return 500"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/general-error")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        error = response.json()["error"]

        assert error["code"] == "INTERNAL_SERVER_ERROR"
        assert error["http_status"] == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.integration
class TestErrorMessageSpec:
    """Test that error messages conform to the specification"""

    def test_error_messages_are_not_empty(self, app_with_handlers):
        """Test that all error responses include non-empty messages"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        
        endpoints = [
            "/auth-invalid",
            "/auth-expired",
            "/forbidden",
            "/not-found",
            "/conflict",
            "/validation",
            "/business-logic",
            "/service-unavailable",
            "/license-not-found",
            "/license-revoked",
            "/license-expired",
            "/general-error",
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            error = response.json()["error"]
            
            assert error["message"], f"Error message is empty for {endpoint}"
            assert isinstance(error["message"], str), f"Error message is not a string for {endpoint}"
            assert len(error["message"]) > 0, f"Error message has zero length for {endpoint}"

    def test_validation_error_has_descriptive_message(self, app_with_handlers):
        """Test that validation errors have descriptive messages"""
        client = TestClient(app_with_handlers)
        response = client.post("/validate-body", json={"invalid": "data"})
        
        error = response.json()["error"]
        assert error["message"] == "Validation error"
        assert len(error["details"]) > 0
        
        # Validate detail messages are descriptive
        for detail in error["details"]:
            assert detail["message"], "Detail message is empty"
            assert isinstance(detail["message"], str), "Detail message is not a string"

    def test_authentication_errors_have_descriptive_messages(self, app_with_handlers):
        """Test that authentication errors have clear, descriptive messages"""
        client = TestClient(app_with_handlers)
        
        # Test AUTH_INVALID
        response = client.get("/auth-invalid")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "credential" in error["message"].lower() or "auth" in error["message"].lower()
        
        # Test AUTH_EXPIRED
        response = client.get("/auth-expired")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "expired" in error["message"].lower() or "token" in error["message"].lower()
        
        # Test FORBIDDEN
        response = client.get("/forbidden")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "access" in error["message"].lower() or "denied" in error["message"].lower()

    def test_resource_errors_have_descriptive_messages(self, app_with_handlers):
        """Test that resource-related errors have clear messages"""
        client = TestClient(app_with_handlers)
        
        # Test RESOURCE_NOT_FOUND
        response = client.get("/not-found")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "not found" in error["message"].lower() or "resource" in error["message"].lower()
        
        # Test RESOURCE_CONFLICT
        response = client.get("/conflict")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "conflict" in error["message"].lower() or "resource" in error["message"].lower()

    def test_license_errors_have_descriptive_messages(self, app_with_handlers):
        """Test that license-related errors have clear messages"""
        client = TestClient(app_with_handlers)
        
        # Test LICENSE_NOT_FOUND
        response = client.get("/license-not-found")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "license" in error["message"].lower()
        
        # Test LICENSE_REVOKED
        response = client.get("/license-revoked")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "license" in error["message"].lower()
        
        # Test LICENSE_EXPIRED
        response = client.get("/license-expired")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "license" in error["message"].lower()

    def test_server_errors_have_descriptive_messages(self, app_with_handlers):
        """Test that server errors have informative messages (but not sensitive)"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        
        # Test SERVICE_UNAVAILABLE
        response = client.get("/service-unavailable")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        assert "service" in error["message"].lower() or "unavailable" in error["message"].lower() or "down" in error["message"].lower()
        
        # Test INTERNAL_ERROR - should not expose internal details
        response = client.get("/general-error")
        error = response.json()["error"]
        assert error["message"]  # Non-empty
        # Ensure it doesn't expose the actual exception details
        assert "Unexpected error" not in error["message"] or error["message"] == "An unexpected error occurred"

    def test_error_messages_consistent_with_error_code(self, app_with_handlers):
        """Test that error messages are semantically related to their error code"""
        client = TestClient(app_with_handlers)
        
        test_cases = [
            ("/auth-invalid", ErrorCode.AUTH_INVALID, "credentials"),
            ("/auth-expired", ErrorCode.AUTH_EXPIRED, "expired"),
            ("/forbidden", ErrorCode.FORBIDDEN, "access"),
            ("/not-found", ErrorCode.RESOURCE_NOT_FOUND, "not found"),
            ("/conflict", ErrorCode.RESOURCE_CONFLICT, "conflict"),
            ("/service-unavailable", ErrorCode.SERVICE_UNAVAILABLE, "down"),
        ]
        
        for endpoint, expected_code, message_keyword in test_cases:
            response = client.get(endpoint)
            error = response.json()["error"]
            
            assert error["code"] == expected_code.value, f"Wrong code for {endpoint}"
            assert message_keyword.lower() in error["message"].lower(), (
                f"Error message '{error['message']}' for {endpoint} "
                f"does not contain expected keyword '{message_keyword}'"
            )

    def test_error_message_length_reasonable(self):
        """Test that error messages are reasonable length (not too terse, not too verbose)"""
        # Test exception classes and their default messages
        exception_classes = [
            ValidationException,
            AuthenticationException,
            AuthExpiredException,
            AuthorizationException,
            NotFoundException,
            ConflictException,
            BusinessLogicException,
            ServiceUnavailableException,
            LicenseNotFoundException,
            LicenseRevokedException,
            LicenseExpiredException,
        ]
        
        for exc_class in exception_classes:
            exc_instance = exc_class()
            message = exc_instance.message
            assert len(message) >= 10, (
                f"Error message for {exc_class.__name__} is too terse: '{message}' ({len(message)} chars)"
            )
            assert len(message) <= 200, (
                f"Error message for {exc_class.__name__} is too verbose: '{message}' ({len(message)} chars)"
            )

    @pytest.mark.parametrize("endpoint,expected_message", [
        pytest.param("/auth-invalid", "Invalid credentials", id="auth_invalid"),
        pytest.param("/auth-expired", "Token has expired", id="auth_expired"),
        pytest.param("/forbidden", "Access denied", id="forbidden"),
        pytest.param("/not-found", "Resource not found", id="resource_not_found"),
        pytest.param("/conflict", "Resource conflict", id="resource_conflict"),
        pytest.param("/validation", "Validation failed", id="validation_error"),
        pytest.param("/business-logic", "Cannot process request", id="business_logic_error"),
        pytest.param("/service-unavailable", "Database is down", id="service_unavailable"),
        pytest.param("/license-not-found", "No active license", id="license_not_found"),
        pytest.param("/license-revoked", "License was revoked", id="license_revoked"),
        pytest.param("/license-expired", "License has expired", id="license_expired"),
    ])
    def test_raised_error_messages_roundtrip_correctly(self, app_with_handlers, endpoint, expected_message):
        """Test that the exact message passed to exception is returned in response"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get(endpoint)
        error = response.json()["error"]
        
        assert error["message"] == expected_message, (
            f"Endpoint {endpoint} returned message '{error['message']}', "
            f"expected '{expected_message}'"
        )
