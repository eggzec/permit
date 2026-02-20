from typing import Any, Optional

from app.schemas.response import ErrorCode


class APIException(Exception):
    """Base exception for API errors"""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        http_status: int,
        details: Optional[list[dict[str, Any]]] = None,
    ):
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
        details: Optional[list[dict[str, Any]]] = None,
    ):
        super().__init__(
            error_code=ErrorCode.VALIDATION_FAILED,
            message=message,
            http_status=422,
            details=details,
        )


class AuthenticationException(APIException):
    """Authentication error"""

    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(
            error_code=ErrorCode.AUTH_INVALID,
            message=message,
            http_status=401,
        )


class AuthorizationException(APIException):
    """Authorization error"""

    def __init__(self, message: str = "Access denied"):
        super().__init__(
            error_code=ErrorCode.FORBIDDEN,
            message=message,
            http_status=403,
        )


class NotFoundException(APIException):
    """Resource not found error"""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            message=message,
            http_status=404,
        )


class ConflictException(APIException):
    """Resource conflict error"""

    def __init__(self, message: str = "Resource conflict"):
        super().__init__(
            error_code=ErrorCode.RESOURCE_CONFLICT,
            message=message,
            http_status=409,
        )


class BusinessLogicException(APIException):
    """Business logic error"""

    def __init__(
        self,
        message: str = "Business logic error",
        details: Optional[list[dict[str, Any]]] = None,
    ):
        super().__init__(
            error_code=ErrorCode.BUSINESS_LOGIC_ERROR,
            message=message,
            http_status=422,
            details=details,
        )
