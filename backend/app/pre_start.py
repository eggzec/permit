import logging

from tenacity import (
    after_log,
    before_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from app.core.config import settings
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARNING),
    retry=retry_if_exception_type(Exception)
    & ~retry_if_exception_type(NotImplementedError)
    & ~retry_if_exception_type(RuntimeError),
)
def init() -> None:
    """code to do the pre-start service"""
    # Create a temporary pool for connectivity check
    pool = None
    try:
        pool = ConnectionPool(settings.DATABASE_DSN)
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        logger.info("Database connectivity check successful")
    except Exception:
        logger.exception("Database connectivity check failed")
        raise
    finally:
        if pool is not None:
            pool.close()


def main() -> None:
    logger.info("Initializing service")
    init()
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()
