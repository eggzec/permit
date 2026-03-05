"""
Unit tests for exception classes in app.core.exceptions.

Covers: error codes, HTTP status codes, base-class parameter storage,
details defaulting, custom details, custom messages, and default message lengths.
"""

import pytest
from fastapi import status

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
from app.schemas.response import ErrorCode


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class,expected_code",
    [
        pytest.param(
            ValidationException,
            ErrorCode.VALIDATION_FAILED,
            id="validation_exception",
        ),
        pytest.param(
            AuthenticationException,
            ErrorCode.AUTH_INVALID,
            id="authentication_exception",
        ),
        pytest.param(
            AuthExpiredException,
            ErrorCode.AUTH_EXPIRED,
            id="auth_expired_exception",
        ),
        pytest.param(
            AuthorizationException,
            ErrorCode.FORBIDDEN,
            id="authorization_exception",
        ),
        pytest.param(
            NotFoundException,
            ErrorCode.RESOURCE_NOT_FOUND,
            id="not_found_exception",
        ),
        pytest.param(
            ConflictException,
            ErrorCode.RESOURCE_CONFLICT,
            id="conflict_exception",
        ),
        pytest.param(
            BusinessLogicException,
            ErrorCode.BUSINESS_LOGIC_ERROR,
            id="business_logic_exception",
        ),
        pytest.param(
            ServiceUnavailableException,
            ErrorCode.SERVICE_UNAVAILABLE,
            id="service_unavailable_exception",
        ),
        pytest.param(
            LicenseNotFoundException,
            ErrorCode.LICENSE_NOT_FOUND,
            id="license_not_found_exception",
        ),
        pytest.param(
            LicenseRevokedException,
            ErrorCode.LICENSE_REVOKED,
            id="license_revoked_exception",
        ),
        pytest.param(
            LicenseExpiredException,
            ErrorCode.LICENSE_EXPIRED,
            id="license_expired_exception",
        ),
    ],
)
def test_exception_has_correct_error_code(exception_class, expected_code):
    """Each exception class must carry the expected error_code."""
    exc = exception_class()
    assert exc.error_code == expected_code, (
        f"{exception_class.__name__} has error_code={exc.error_code.value}, "
        f"expected {expected_code.value}"
    )


# ---------------------------------------------------------------------------
# HTTP status codes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class,expected_status",
    [
        pytest.param(
            ValidationException,
            # Starlette <0.48 compatibility: use getattr fallback to literal 422
            getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            id="validation_exception",
        ),
        pytest.param(
            AuthenticationException,
            status.HTTP_401_UNAUTHORIZED,
            id="authentication_exception",
        ),
        pytest.param(
            AuthExpiredException,
            status.HTTP_401_UNAUTHORIZED,
            id="auth_expired_exception",
        ),
        pytest.param(
            AuthorizationException,
            status.HTTP_403_FORBIDDEN,
            id="authorization_exception",
        ),
        pytest.param(
            NotFoundException,
            status.HTTP_404_NOT_FOUND,
            id="not_found_exception",
        ),
        pytest.param(
            ConflictException,
            status.HTTP_409_CONFLICT,
            id="conflict_exception",
        ),
        pytest.param(
            BusinessLogicException,
            # Starlette <0.48 compatibility: use getattr fallback to literal 422
            getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            id="business_logic_exception",
        ),
        pytest.param(
            ServiceUnavailableException,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            id="service_unavailable_exception",
        ),
        pytest.param(
            LicenseNotFoundException,
            status.HTTP_404_NOT_FOUND,
            id="license_not_found_exception",
        ),
        pytest.param(
            LicenseRevokedException,
            status.HTTP_409_CONFLICT,
            id="license_revoked_exception",
        ),
        pytest.param(
            LicenseExpiredException,
            status.HTTP_409_CONFLICT,
            id="license_expired_exception",
        ),
    ],
)
def test_exception_has_correct_http_status(exception_class, expected_status):
    """Each exception class must carry the expected http_status."""
    exc = exception_class()
    assert exc.http_status == expected_status, (
        f"{exception_class.__name__} has http_status={exc.http_status}, "
        f"expected {expected_status}"
    )


# ---------------------------------------------------------------------------
# Base class — parameter storage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_exception_base_class_stores_all_parameters():
    """APIException must store all constructor arguments and pass message to str()."""
    exc = APIException(
        error_code=ErrorCode.VALIDATION_FAILED,
        message="Test error",
        http_status=status.HTTP_400_BAD_REQUEST,
        details=[{"field": "test", "message": "error"}],
    )
    assert exc.error_code == ErrorCode.VALIDATION_FAILED, (
        f"Expected error_code VALIDATION_FAILED, got {exc.error_code}"
    )
    assert exc.message == "Test error", (
        f"Expected message 'Test error', got '{exc.message}'"
    )
    assert exc.http_status == status.HTTP_400_BAD_REQUEST, (
        f"Expected http_status 400, got {exc.http_status}"
    )
    assert exc.details == [{"field": "test", "message": "error"}], (
        f"Expected details with test field, got {exc.details}"
    )
    assert str(exc) == "Test error", (
        f"Expected str(exc) to return message, got '{str(exc)}'"
    )


# ---------------------------------------------------------------------------
# Details defaulting
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_exception_with_details_none_defaults_to_empty():
    """APIException(details=None) must produce an empty details list."""
    exc = APIException(
        error_code=ErrorCode.VALIDATION_FAILED,
        message="Test error",
        http_status=status.HTTP_400_BAD_REQUEST,
        details=None,
    )
    assert exc.details == [], (
        f"APIException with details=None should produce [], got {exc.details}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class",
    [
        pytest.param(ValidationException, id="validation_exception"),
        pytest.param(BusinessLogicException, id="business_logic_exception"),
    ],
)
def test_exception_with_details_none_defaults_to_empty_list(exception_class):
    """Exceptions that accept a details kwarg must treat details=None as []."""
    exc = exception_class(details=None)
    assert exc.details == [], (
        f"{exception_class.__name__} with details=None should produce [], "
        f"got {exc.details}"
    )


# ---------------------------------------------------------------------------
# Custom details
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class,message,details",
    [
        pytest.param(
            ValidationException,
            "Validation failed",
            [
                {"field": "email", "message": "Invalid email"},
                {"field": "password", "message": "Too short"},
            ],
            id="validation_exception",
        ),
        pytest.param(
            BusinessLogicException,
            "Payment failed",
            [{"field": "billing", "message": "Insufficient credits"}],
            id="business_logic_exception",
        ),
    ],
)
def test_exception_stores_custom_details(exception_class, message, details):
    """Exceptions must store the exact message and details passed at construction."""
    exc = exception_class(message=message, details=details)
    assert exc.message == message, f"Expected message '{message}', got '{exc.message}'"
    assert exc.details == details, f"Expected details {details}, got {exc.details}"


# ---------------------------------------------------------------------------
# Custom messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class",
    [
        pytest.param(AuthenticationException, id="authentication_exception"),
        pytest.param(AuthExpiredException, id="auth_expired_exception"),
        pytest.param(AuthorizationException, id="authorization_exception"),
        pytest.param(NotFoundException, id="not_found_exception"),
        pytest.param(ConflictException, id="conflict_exception"),
        pytest.param(ServiceUnavailableException, id="service_unavailable_exception"),
        pytest.param(LicenseNotFoundException, id="license_not_found_exception"),
        pytest.param(LicenseRevokedException, id="license_revoked_exception"),
        pytest.param(LicenseExpiredException, id="license_expired_exception"),
    ],
)
def test_simple_exception_accepts_custom_message(exception_class):
    """Positional-message exceptions must store whatever message is passed."""
    custom_msg = f"Custom message for {exception_class.__name__}"
    exc = exception_class(custom_msg)
    assert exc.message == custom_msg, (
        f"Expected message '{custom_msg}', got '{exc.message}'"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class",
    [
        pytest.param(ValidationException, id="validation_exception"),
        pytest.param(BusinessLogicException, id="business_logic_exception"),
    ],
)
def test_parameterized_exception_accepts_custom_message(exception_class):
    """Keyword-message exceptions must store whatever message is passed."""
    custom_msg = f"Custom message for {exception_class.__name__}"
    exc = exception_class(message=custom_msg)
    assert exc.message == custom_msg, (
        f"Expected message '{custom_msg}', got '{exc.message}'"
    )


# ---------------------------------------------------------------------------
# Default message sanity
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class",
    [
        pytest.param(ValidationException, id="validation_exception"),
        pytest.param(AuthenticationException, id="authentication_exception"),
        pytest.param(AuthExpiredException, id="auth_expired_exception"),
        pytest.param(AuthorizationException, id="authorization_exception"),
        pytest.param(NotFoundException, id="not_found_exception"),
        pytest.param(ConflictException, id="conflict_exception"),
        pytest.param(BusinessLogicException, id="business_logic_exception"),
        pytest.param(ServiceUnavailableException, id="service_unavailable_exception"),
        pytest.param(LicenseNotFoundException, id="license_not_found_exception"),
        pytest.param(LicenseRevokedException, id="license_revoked_exception"),
        pytest.param(LicenseExpiredException, id="license_expired_exception"),
    ],
)
def test_exception_default_message_has_reasonable_length(exception_class):
    """Default messages must be between 5 and 200 characters."""
    message = exception_class().message
    assert message, f"{exception_class.__name__} has empty default message"
    assert 5 <= len(message) <= 200, (
        f"{exception_class.__name__} message '{message}' is outside "
        f"reasonable 5-200 character range ({len(message)} chars)"
    )


# ---------------------------------------------------------------------------
# Inheritance chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_exception_is_subclass_of_exception():
    """APIException must inherit from Exception so the general_exception_handler
    fallback can catch it if the api_exception_handler is ever misconfigured."""
    assert issubclass(APIException, Exception), (
        "APIException must be a subclass of Exception"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "exception_class",
    [
        pytest.param(AuthenticationException, id="authentication_exception"),
        pytest.param(AuthExpiredException, id="auth_expired_exception"),
        pytest.param(AuthorizationException, id="authorization_exception"),
        pytest.param(NotFoundException, id="not_found_exception"),
        pytest.param(ConflictException, id="conflict_exception"),
        pytest.param(ValidationException, id="validation_exception"),
        pytest.param(BusinessLogicException, id="business_logic_exception"),
        pytest.param(ServiceUnavailableException, id="service_unavailable_exception"),
        pytest.param(LicenseNotFoundException, id="license_not_found_exception"),
        pytest.param(LicenseRevokedException, id="license_revoked_exception"),
        pytest.param(LicenseExpiredException, id="license_expired_exception"),
    ],
)
def test_concrete_exception_is_subclass_of_api_exception(exception_class):
    """Every concrete exception class must be a subclass of APIException so that
    api_exception_handler catches it.  If this invariant breaks, those exceptions
    silently fall through to general_exception_handler and return 500s."""
    assert issubclass(exception_class, APIException), (
        f"{exception_class.__name__} is not a subclass of APIException; "
        f"api_exception_handler will not catch it"
    )
