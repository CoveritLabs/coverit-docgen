import logging
import logging.config
from src.core.config import Settings


def setup_logging(settings: Settings) -> None:
    """
    Configures the global Python logging system based on the environment.
    Uses dictionary configuration for clean, predictable output.
    """

    log_level = "DEBUG" if settings.debug else "INFO"

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                # Format: [2024-05-12 10:22:34] [INFO] [src.tasks.labeling] - Message
                "format": "%(asctime)s [%(levelname)s] [%(name)s] - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                # In heavily scaled production, you often use JSON formatters here
                # so tools like Datadog/ELK can parse the logs automatically.
                "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
            },
        },
        "handlers": {
            "console": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "standard",  # Switch to 'json' if sending logs to Datadog
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            # Our application logs
            "src": {
                "handlers": ["console"],
                "level": log_level,
                "propagate": False,
            },
            "api": {
                "handlers": ["console"],
                "level": log_level,
                "propagate": False,
            },
            # Third-party loggers (mute their noise)
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "WARNING",  # We mute Uvicorn's default access logs because our custom Middleware handles it better
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "handlers": ["console"],
                "level": "WARNING",  # Change to DEBUG if you want to see all SQL queries
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }

    logging.config.dictConfig(logging_config)
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging initialized. Environment: {settings.environment}, Level: {log_level}"
    )
