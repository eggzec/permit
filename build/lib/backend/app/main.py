import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
import logging

from app.api.main import api_router
from app.core.config import settings
from app.core.exceptions import APIException
from app.schemas.response import ErrorCode
from psycopg_pool import ConnectionPool


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database pool")
    pool = ConnectionPool(settings.DATABASE_DSN)
    
    # Connectivity check
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        logger.info("Database connectivity check successful")
    except Exception as e:
        logger.exception("Database connectivity check failed")
        pool.close()
        raise RuntimeError("Database connectivity check failed") from e
    
    app.state.db_pool = pool
    logger.info("Database pool initialized")
    
    yield
    
    # Shutdown
    logger.info("Closing database pool")
    pool.close()
    logger.info("Database pool closed")


def custom_generate_unique_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


API_V1_STR = "/api/v1"

# also use the lifespan with this to do the prestart and shutdown events
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.include_router(api_router, prefix=API_V1_STR)


# ============================================================================
# Request ID Middleware
# ============================================================================


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add a unique request_id to each request context"""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ============================================================================
# Exception Handlers
# ============================================================================


def get_request_id_from_context() -> str:
    """Extract request_id from request context if available"""
    try:
        from fastapi import Request
        from starlette.datastructures import Headers

        # Fallback request_id
        return str(uuid.uuid4())
    except Exception:
        return str(uuid.uuid4())


@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException):
    """Handle custom API exceptions"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    logger.warning(
        f"API Exception: {exc.error_code} - {exc.message}",
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
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # Parse validation errors
    details = []
    for error in exc.errors():
        details.append(
            {
                "field": ".".join(str(loc) for loc in error["loc"][1:]),
                "message": error["msg"],
            }
        )

    logger.warning(
        f"Validation Error: {len(details)} validation errors",
        extra={
            "request_id": request_id,
            "validation_errors": details,
        },
    )

    error_response = {
        "error": {
            "code": ErrorCode.VALIDATION_FAILED.value,
            "message": "Validation error",
            "http_status": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "details": details,
            "request_id": request_id,
        }
    }

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all uncaught exceptions"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # Log the full traceback server-side
    logger.exception(
        f"Unexpected error: {str(exc)}",
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
    )

