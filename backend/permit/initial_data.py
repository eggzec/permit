import logging

logger = logging.getLogger(__name__)


def init() -> None:
    ...

def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
