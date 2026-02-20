from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.routing import APIRoute
import logging

from app.api.main import api_router
from app.core.config import settings
from psycopg_pool import ConnectionPool


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
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
    title=settings.PROJECT_NAME,
    openapi_url=f"{API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.include_router(api_router, prefix=API_V1_STR)
