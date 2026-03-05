from typing import Any

from starlette import status

from app.schemas.response import ErrorCode


class APIException(Exception):  # noqa: N818
    """Base exception for API errors"""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        http_status: int,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.details = details or []
        super().__init__(self.message)


class ValidationException(APIException):
    """Validation error"""

    def __init__(
        self,
        message: str = "Invalid request parameters",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.VALIDATION_FAILED,
            message=message,
            # Starlette <0.48 compat: fallback to 422
            http_status=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            details=details,
        )


class AuthenticationException(APIException):
    """Authentication error"""

    def __init__(self, message: str = "Invalid credentials") -> None:
        super().__init__(
            error_code=ErrorCode.AUTH_INVALID,
            message=message,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )


class AuthorizationException(APIException):
    """Authorization error"""

    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(
            error_code=ErrorCode.FORBIDDEN,
            message=message,
            http_status=status.HTTP_403_FORBIDDEN,
        )


class NotFoundException(APIException):
    """Resource not found error"""

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            message=message,
            http_status=status.HTTP_404_NOT_FOUND,
        )


class ConflictException(APIException):
    """Resource conflict error"""

    def __init__(self, message: str = "Resource conflict") -> None:
        super().__init__(
            error_code=ErrorCode.RESOURCE_CONFLICT,
            message=message,
            http_status=status.HTTP_409_CONFLICT,
        )


class BusinessLogicException(APIException):
    """Business logic error"""

    def __init__(
        self,
        message: str = "Business logic error",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.BUSINESS_LOGIC_ERROR,
            message=message,
            # Starlette <0.48 compat: fallback to 422
            http_status=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            details=details,
        )


class ServiceUnavailableException(APIException):
    """Service unavailable error"""

    def __init__(
        self, message: str = "Service temporarily unavailable"
    ) -> None:
        super().__init__(
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            message=message,
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class AuthExpiredException(APIException):
    """Authentication token expired error"""

    def __init__(
        self, message: str = "Authentication token has expired"
    ) -> None:
        super().__init__(
            error_code=ErrorCode.AUTH_EXPIRED,
            message=message,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )


class LicenseNotFoundException(APIException):
    """License not found error"""

    def __init__(self, message: str = "License not found") -> None:
        super().__init__(
            error_code=ErrorCode.LICENSE_NOT_FOUND,
            message=message,
            http_status=status.HTTP_404_NOT_FOUND,
        )


class LicenseRevokedException(APIException):
    """License has been revoked error"""

    def __init__(self, message: str = "License has been revoked") -> None:
        super().__init__(
            error_code=ErrorCode.LICENSE_REVOKED,
            message=message,
            http_status=status.HTTP_409_CONFLICT,
        )


class LicenseExpiredException(APIException):
    """License has expired error"""

    def __init__(self, message: str = "License has expired") -> None:
        super().__init__(
            error_code=ErrorCode.LICENSE_EXPIRED,
            message=message,
            http_status=status.HTTP_409_CONFLICT,
        )
