from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Standard error codes for the API"""

    # Validation errors
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"

    # Authentication & Authorization errors
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"

    # Resource errors
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"

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

    field: Optional[str] = Field(None, description="Field name if validation error")
    message: str = Field(..., description="Detailed error message")


class ErrorResponse(BaseModel):
    """Standard error response envelope"""

    error: dict[str, Any] = Field(
        ...,
        description="Error information containing code, message, http_status, details, and request_id",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": "Invalid request parameters",
                    "http_status": 400,
                    "details": [{"field": "email", "message": "Invalid email format"}],
                    "request_id": "req-123456789",
                }
            }
        }
