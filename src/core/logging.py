import logging
import logging.config
from pathlib import Path
from src.core.config import Settings


def setup_logging(settings: Settings) -> None:
    """
    Configures the global Python logging system based on the environment.
    Uses dictionary configuration for clean, predictable output.
    """

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = "DEBUG" if settings.debug else "INFO"

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] [%(name)s] - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
            },
        },
        "handlers": {
            "console": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "level": log_level,
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "filename": "logs/worker.log",  # Saves inside the logs folder
                "maxBytes": 10485760,  # 10 MB size limit per file
                "backupCount": 5,  # Keeps the last 5 files (worker.log.1, worker.log.2...)
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "src": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "api": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "file"],
                "level": "WARNING",
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "handlers": ["console", "file"],
                "level": "WARNING",
                "propagate": False,
            },
        },
        "root": {
            # Catch-all for any other loggers
            "handlers": ["console", "file"],
            "level": "INFO",
        },
    }

    logging.config.dictConfig(logging_config)
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging initialized. Environment: {settings.environment}, Level: {log_level}"
    )
