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
    LicenseKeyGenerationError,
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
    ("exception_class", "expected_code"),
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
        pytest.param(
            LicenseKeyGenerationError,
            ErrorCode.LICENSE_KEY_GENERATION_ERROR,
            id="license_key_generation_error",
        ),
    ],
)
def test_exception_has_correct_error_code(exception_class, expected_code):
    """
    Verifies that each concrete exception class in `app.core.exceptions` exposes
    the expected `error_code`. This matters because the error code is the
    machine-readable part of the public API error contract.

    Covers:
        - concrete exception classes in `app.core.exceptions`

    Rationale:
        A parametrized class matrix keeps the exception-to-code mapping documented in one place.

    Fixtures:
        None.

    Parametrize:
        exception_class: Exception class being instantiated.
        expected_code: `ErrorCode` value expected on the exception instance.
        Cases:
            - <id="validation_exception"> — validation error mapping.
            - <id="authentication_exception"> — invalid-authentication mapping.
            - <id="auth_expired_exception"> — expired-authentication mapping.
            - <id="authorization_exception"> — authorization mapping.
            - <id="not_found_exception"> — generic not-found mapping.
            - <id="conflict_exception"> — generic conflict mapping.
            - <id="business_logic_exception"> — business-logic mapping.
            - <id="service_unavailable_exception"> — service-unavailable mapping.
            - <id="license_not_found_exception"> — license-not-found mapping.
            - <id="license_revoked_exception"> — license-revoked mapping.
            - <id="license_expired_exception"> — license-expired mapping.
            - <id="license_key_generation_error"> — license-key-generation mapping.
    """
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
    ("exception_class", "expected_status"),
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
            ConflictException, status.HTTP_409_CONFLICT, id="conflict_exception"
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
        pytest.param(
            LicenseKeyGenerationError,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            id="license_key_generation_error",
        ),
    ],
)
def test_exception_has_correct_http_status(exception_class, expected_status):
    """
    Verifies that each concrete exception class in `app.core.exceptions` exposes
    the expected HTTP status code. This matters because the status code is part
    of the API error envelope emitted by the exception handlers.

    Covers:
        - concrete exception classes in `app.core.exceptions`

    Rationale:
        The parametrized matrix keeps the exception-to-status mapping readable and avoids duplicate single-case tests.

    Fixtures:
        None.

    Parametrize:
        exception_class: Exception class being instantiated.
        expected_status: HTTP status code expected on the exception instance.
        Cases:
            - <id="validation_exception"> — validation status mapping.
            - <id="authentication_exception"> — invalid-authentication status mapping.
            - <id="auth_expired_exception"> — expired-authentication status mapping.
            - <id="authorization_exception"> — authorization status mapping.
            - <id="not_found_exception"> — generic not-found status mapping.
            - <id="conflict_exception"> — generic conflict status mapping.
            - <id="business_logic_exception"> — business-logic status mapping.
            - <id="service_unavailable_exception"> — service-unavailable status mapping.
            - <id="license_not_found_exception"> — license-not-found status mapping.
            - <id="license_revoked_exception"> — license-revoked status mapping.
            - <id="license_expired_exception"> — license-expired status mapping.
            - <id="license_key_generation_error"> — license-key-generation status mapping.
    """
    exc = exception_class()
    assert exc.http_status == expected_status, (
        f"{exception_class.__name__} has http_status={exc.http_status}, "
        f"expected {expected_status}"
    )


# ---------------------------------------------------------------------------
# Base class — parameter storage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_exception_base_class_stores_all_parameters(faker):
    """
    Verifies that `app.core.exceptions.APIException` stores the constructor
    arguments that drive the API error contract. This matters because all
    concrete exception types inherit this state and the exception handlers
    serialize it directly.

    Covers:
        - `app.core.exceptions.APIException`

    Rationale:
        The base class is instantiated directly so the storage contract is asserted independently of any subclass defaults.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate message and detail values.
    """
    msg = faker.sentence()
    field = faker.word()
    detail_msg = faker.sentence()
    exc = APIException(
        error_code=ErrorCode.VALIDATION_FAILED,
        message=msg,
        http_status=status.HTTP_400_BAD_REQUEST,
        details=[{"field": field, "message": detail_msg}],
    )
    assert exc.error_code == ErrorCode.VALIDATION_FAILED, (
        f"Expected error_code VALIDATION_FAILED, got {exc.error_code}"
    )
    assert exc.message == msg, f"Expected message '{msg}', got '{exc.message}'"
    assert exc.http_status == status.HTTP_400_BAD_REQUEST, (
        f"Expected http_status 400, got {exc.http_status}"
    )
    assert exc.details == [{"field": field, "message": detail_msg}], (
        f"Expected details with test field, got {exc.details}"
    )
    assert str(exc) == msg, (
        f"Expected str(exc) to return message, got '{exc!s}'"
    )


# ---------------------------------------------------------------------------
# Details defaulting
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_exception_with_details_none_defaults_to_empty(faker):
    """
    Verifies that `app.core.exceptions.APIException` normalizes `details=None`
    into an empty list. This matters because handlers expect a list-shaped
    details field even when no details are provided.

    Covers:
        - `app.core.exceptions.APIException`

    Rationale:
        The test isolates the `details=None` case on the base class because that normalization is inherited by downstream exceptions.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the exception message.
    """
    exc = APIException(
        error_code=ErrorCode.VALIDATION_FAILED,
        message=faker.sentence(),
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
    """
    Verifies that detail-bearing concrete exceptions normalize `details=None`
    into an empty list. This matters because callers should get the same details
    shape whether they use the base class or concrete subclasses.

    Covers:
        - `app.core.exceptions.ValidationException`
        - `app.core.exceptions.BusinessLogicException`

    Rationale:
        A small parametrized matrix is enough because the subclasses share the same details-defaulting contract.

    Fixtures:
        None.

    Parametrize:
        exception_class: Concrete exception class that accepts a `details` keyword.
        Cases:
            - <id="validation_exception"> — validation exception defaulting.
            - <id="business_logic_exception"> — business-logic exception defaulting.
    """
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
    ("exception_class", "message", "details"),
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
    """
    Verifies that detail-bearing concrete exceptions preserve the custom message
    and detail payload passed at construction. This matters because handlers
    serialize these fields directly into the API response.

    Covers:
        - `app.core.exceptions.ValidationException`
        - `app.core.exceptions.BusinessLogicException`

    Rationale:
        The parametrized cases document both detail-bearing exception families that expose this constructor contract.

    Fixtures:
        None.

    Parametrize:
        exception_class: Concrete exception class under test.
        message: Custom message passed into the exception constructor.
        details: Custom detail payload expected to round-trip unchanged.
        Cases:
            - <id="validation_exception"> — validation exception with two detail entries.
            - <id="business_logic_exception"> — business-logic exception with one detail entry.
    """
    exc = exception_class(message=message, details=details)
    assert exc.message == message, (
        f"Expected message '{message}', got '{exc.message}'"
    )
    assert exc.details == details, (
        f"Expected details {details}, got {exc.details}"
    )


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
        pytest.param(
            ServiceUnavailableException, id="service_unavailable_exception"
        ),
        pytest.param(
            LicenseNotFoundException, id="license_not_found_exception"
        ),
        pytest.param(LicenseRevokedException, id="license_revoked_exception"),
        pytest.param(LicenseExpiredException, id="license_expired_exception"),
        pytest.param(
            LicenseKeyGenerationError, id="license_key_generation_error"
        ),
    ],
)
def test_simple_exception_accepts_custom_message(exception_class, faker):
    """
    Verifies that positional-message exception classes preserve the custom
    message passed to their constructor. This matters because the exception
    handlers expose these messages directly to API clients for handled
    exceptions.

    Covers:
        - positional-message concrete exception classes in `app.core.exceptions`

    Rationale:
        The parametrized matrix keeps the shared custom-message contract aligned across all positional-message subclasses.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the custom message.

    Parametrize:
        exception_class: Positional-message exception class under test.
        Cases:
            - <id="authentication_exception"> — invalid-authentication exception.
            - <id="auth_expired_exception"> — expired-authentication exception.
            - <id="authorization_exception"> — authorization exception.
            - <id="not_found_exception"> — generic not-found exception.
            - <id="conflict_exception"> — generic conflict exception.
            - <id="service_unavailable_exception"> — service-unavailable exception.
            - <id="license_not_found_exception"> — license-not-found exception.
            - <id="license_revoked_exception"> — license-revoked exception.
            - <id="license_expired_exception"> — license-expired exception.
            - <id="license_key_generation_error"> — license-key-generation exception.
    """
    custom_msg = faker.sentence()
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
def test_parameterized_exception_accepts_custom_message(exception_class, faker):
    """
    Verifies that keyword-message exception classes preserve the custom message
    passed to their constructor. This matters because these subclasses expose
    their message through the same API error serialization path as the base
    class.

    Covers:
        - `app.core.exceptions.ValidationException`
        - `app.core.exceptions.BusinessLogicException`

    Rationale:
        A small parametrized set keeps the shared keyword-message constructor contract explicit.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the custom message.

    Parametrize:
        exception_class: Keyword-message exception class under test.
        Cases:
            - <id="validation_exception"> — validation exception custom message.
            - <id="business_logic_exception"> — business-logic exception custom message.
    """
    custom_msg = faker.sentence()
    exc = exception_class(message=custom_msg)
    assert exc.message == custom_msg, (
        f"Expected message '{custom_msg}', got '{exc.message}'"
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
        pytest.param(
            ServiceUnavailableException, id="service_unavailable_exception"
        ),
        pytest.param(
            LicenseNotFoundException, id="license_not_found_exception"
        ),
        pytest.param(LicenseRevokedException, id="license_revoked_exception"),
        pytest.param(LicenseExpiredException, id="license_expired_exception"),
        pytest.param(
            LicenseKeyGenerationError, id="license_key_generation_error"
        ),
    ],
)
def test_concrete_exception_is_subclass_of_api_exception(exception_class):
    """
    Verifies that every concrete exception class subclasses
    `app.core.exceptions.APIException`. This matters because the API exception
    handler relies on that inheritance chain to catch handled application errors

    Covers:
        - concrete exception classes in `app.core.exceptions`

    Rationale:
        The inheritance check is expressed directly because the contract is structural rather than behavioral.

    Fixtures:
        None.

    Parametrize:
        exception_class: Concrete exception class whose inheritance chain is being checked.
        Cases:
            - <id="authentication_exception"> — invalid-authentication inheritance.
            - <id="auth_expired_exception"> — expired-authentication inheritance.
            - <id="authorization_exception"> — authorization inheritance.
            - <id="not_found_exception"> — generic not-found inheritance.
            - <id="conflict_exception"> — generic conflict inheritance.
            - <id="validation_exception"> — validation inheritance.
            - <id="business_logic_exception"> — business-logic inheritance.
            - <id="service_unavailable_exception"> — service-unavailable inheritance.
            - <id="license_not_found_exception"> — license-not-found inheritance.
            - <id="license_revoked_exception"> — license-revoked inheritance.
            - <id="license_expired_exception"> — license-expired inheritance.
            - <id="license_key_generation_error"> — license-key-generation inheritance.
    """
    assert issubclass(exception_class, APIException), (
        f"{exception_class.__name__} is not a subclass of APIException; "
        f"api_exception_handler will not catch it"
    )
