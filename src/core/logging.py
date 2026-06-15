import logging
import logging.config
from pathlib import Path

from src.core.config import Settings


def setup_logging(
    settings: Settings, log_dir: Path | str | None = None
) -> Path:
    """Configure console and rotating-file logging for the process.

    Args:
        settings: Runtime settings controlling environment and log level.
        log_dir: Optional destination override, primarily for tests. By
            default logs are written to the repository/container ``logs``
            directory resolved from this module's absolute location.

    Returns:
        The absolute path of the configured ``worker.log`` file.
    """
    resolved_log_dir = (
        Path(log_dir).resolve()
        if log_dir is not None
        else Path(__file__).resolve().parents[2] / "logs"
    )
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = resolved_log_dir / "worker.log"
    log_level = "DEBUG" if settings.debug else "INFO"

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] [%(name)s] - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
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
                "filename": str(log_file),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "neo4j": {
                "handlers": ["console", "file"],
                "level": "WARNING",
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
            "handlers": ["console", "file"],
            "level": log_level,
        },
    }

    logging.config.dictConfig(logging_config)
    logging.getLogger(__name__).info(
        "Logging initialized. Environment: %s, Level: %s, File: %s",
        settings.environment,
        log_level,
        log_file,
    )
    return log_file
