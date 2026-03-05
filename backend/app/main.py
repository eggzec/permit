import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from psycopg_pool import ConnectionPool

from app.api.main import api_router
from app.api.middlewares import add_request_id
from app.core.config import Settings
from app.core.exception_handlers import (
    api_exception_handler,
    general_exception_handler,
    validation_exception_handler,
)
from app.core.exceptions import APIException


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: RUF029
    # Startup
    logger.info("Initializing settings")
    settings = Settings()
    app.state.settings = settings
    app.title = settings.PROJECT_NAME
    logger.info("Settings initialized")

    logger.info("Initializing database pool")
    pool = ConnectionPool(str(settings.DATABASE_DSN))

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
    title="API",
    openapi_url=f"{API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.include_router(api_router, prefix=API_V1_STR)

app.middleware("http")(add_request_id)

app.add_exception_handler(APIException, api_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)
