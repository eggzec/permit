import uuid
import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import APIException
from app.schemas.response import ErrorCode


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

    error_response = {
        "error": {
            "code": exc.error_code.value,
            "message": exc.message,
            "http_status": exc.http_status,
            "details": exc.details,
            "request_id": request_id,
        }
    }

    return JSONResponse(
        status_code=exc.http_status,
        content=error_response,
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

    error_response = {
        "error": {
            "code": ErrorCode.VALIDATION_FAILED.value,
            "message": "Validation error",
            # Use getattr for compatibility with Starlette <0.48 which lacks HTTP_422_UNPROCESSABLE_CONTENT
            "http_status": getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            "details": details,
            "request_id": request_id,
        }
    }

    return JSONResponse(
        # Use getattr for compatibility with Starlette <0.48 which lacks HTTP_422_UNPROCESSABLE_CONTENT
        status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
        content=error_response,
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

    error_response = {
        "error": {
            "code": ErrorCode.INTERNAL_SERVER_ERROR.value,
            "message": "An unexpected error occurred",
            "http_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "details": [],
            "request_id": request_id,
        }
    }

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response,
        headers={"X-Request-ID": request_id},
    )
