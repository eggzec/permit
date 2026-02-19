import logging

from tenacity import (
    after_log,
    before_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from app.core.db import pool

logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARNING),
    retry=retry_if_exception_type(Exception)
    & ~retry_if_exception_type(NotImplementedError),
)
def init(db_engine) -> None:
    """code to do the pre-start service"""
    if db_engine is None:
        logger.error("Database pool is not initialized")
        raise RuntimeError("Database pool is not initialized")
    try:
        with db_engine.connection() as conn:
            conn.execute("SELECT 1")
        logger.info("Database connectivity check successful")
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}")
        raise RuntimeError(f"Database connectivity check failed: {e}") from e


def main() -> None:
    logger.info("Initializing service")
    init(pool)
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()
