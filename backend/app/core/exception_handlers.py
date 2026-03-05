import uuid
import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import APIException
from app.schemas.response import (
    ErrorBodyResponse,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
)


logger = logging.getLogger(__name__)


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    """Handle custom API exceptions"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    logger.warning(
        "API Exception: %s - %s",
        exc.error_code,
        exc.message,
        extra={"request_id": request_id, "error_code": exc.error_code},
    )

    # Use typed schema to validate error structure
    error_response = ErrorResponse(
        error=ErrorBodyResponse(
            code=exc.error_code,
            message=exc.message,
            http_status=exc.http_status,
            details=_build_error_details(exc.details),
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=exc.http_status,
        content=error_response.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # Parse validation errors
    details = []
    for error in exc.errors():
        field_path = ".".join(str(loc) for loc in error["loc"][1:])
        field = field_path if field_path else None
        details.append(
            {
                "field": field,
                "message": error["msg"],
            }
        )

    logger.warning(
        "Validation Error: %d validation errors",
        len(details),
        extra={
            "request_id": request_id,
            "validation_errors": details,
        },
    )

    # Starlette <0.48 compatibility: use getattr fallback to literal 422
    http_422_unprocessable_content = getattr(
        status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
    )

    # Use typed schema to validate error structure
    error_response = ErrorResponse(
        error=ErrorBodyResponse(
            code=ErrorCode.VALIDATION_FAILED,
            message="Validation error",
            http_status=http_422_unprocessable_content,
            details=_build_error_details(details),
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=http_422_unprocessable_content,
        content=error_response.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle all uncaught exceptions"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # Log the full traceback server-side
    logger.exception(
        "Unexpected error: %s",
        str(exc),
        extra={"request_id": request_id},
    )

    # Use typed schema to validate error structure
    error_response = ErrorResponse(
        error=ErrorBodyResponse(
            code=ErrorCode.INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=[],
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


def _build_error_details(
    details: list[dict | ErrorDetail] | dict | ErrorDetail | None,
) -> list[ErrorDetail]:
    """
    Converts error details (list, dict, ErrorDetail, or None) into a list of ErrorDetail instances.

    Args:
        details: Can be a list of dict/ErrorDetail, a single dict, a single ErrorDetail, or None.
                 Non-dict/non-ErrorDetail entries are converted to string messages.

    Returns:
        List of ErrorDetail instances. Non-dict/non-ErrorDetail entries are preserved as string messages.
    """
    if details is None:
        return []
    normalized = details if isinstance(details, list) else [details]
    result: list[ErrorDetail] = []
    for d in normalized:
        if isinstance(d, ErrorDetail):
            result.append(d)
        elif isinstance(d, dict):
            result.append(
                ErrorDetail(
                    field=d.get("field"),
                    message=d.get("message") or "Unknown error",
                )
            )
        else:
            result.append(ErrorDetail(field=None, message=str(d)))
    return result
