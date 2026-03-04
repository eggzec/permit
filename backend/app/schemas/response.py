from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Standard error codes for the API"""

    # Validation errors
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"

    # Authentication & Authorization errors
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    FORBIDDEN = "FORBIDDEN"

    # Resource errors
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"

    # License errors
    LICENSE_NOT_FOUND = "LICENSE_NOT_FOUND"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"

    # Business logic errors
    BUSINESS_LOGIC_ERROR = "BUSINESS_LOGIC_ERROR"
    INVALID_STATE = "INVALID_STATE"

    # Server errors
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class SuccessResponse(BaseModel, Generic[T]):
    """Generic success response envelope"""

    data: T = Field(..., description="Response data")


class ErrorDetail(BaseModel):
    """Additional error details"""

    field: str | None = Field(None, description="Field name if validation error")
    message: str = Field(..., description="Detailed error message")


class ErrorBodyResponse(BaseModel):
    """Error response body with all required fields"""

    code: ErrorCode = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    http_status: int = Field(..., description="HTTP status code matching the response")
    details: list[ErrorDetail] = Field(
        default_factory=list,
        description="Additional error details for validation errors or other context",
    )
    request_id: str = Field(..., description="Unique request identifier for tracing")


class ErrorResponse(BaseModel):
    """Standard error response envelope"""

    error: ErrorBodyResponse = Field(
        ...,
        description="Error information with code, message, http_status, details, and request_id",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": "Invalid request parameters",
                    "http_status": 422,
                    "details": [{"field": "email", "message": "Invalid email format"}],
                    "request_id": "req-123456789",
                }
            }
        }
    )
