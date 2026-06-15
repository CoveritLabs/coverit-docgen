"""ARQ worker entry point."""

from src.core.config import get_settings
from src.core.logging import setup_logging

settings = get_settings()
setup_logging(settings)

import logging

from arq import cron

from src.core.database import session_manager
from src.core.neo import neo_manager
from src.core.redis import redis_settings
from src.tasks.labeling import (
    task_label_graph,
    task_label_state_by_id,
    task_label_transition_by_id,
)
from src.tasks.poller import cron_poll_unlabeled_data
from src.utils.helpers import parse_cron_string

logger = logging.getLogger("arq.worker")

CRON_HOURS = parse_cron_string(settings.poller_cron_hours)
CRON_MINUTES = parse_cron_string(settings.poller_cron_minutes)


async def startup(ctx: dict) -> None:
    """Initialize database clients and immediately poll for queued work."""
    await session_manager.init()
    neo_manager.init()
    logger.info("Worker initialized database connections")
    await cron_poll_unlabeled_data(ctx)


async def shutdown(ctx: dict) -> None:
    """Close database clients during worker shutdown."""
    await session_manager.close()
    await neo_manager.close()
    logger.info("Worker closed database connections")


class WorkerSettings:
    """ARQ hooks, tasks, schedule, and Redis connection settings."""

    on_startup = startup
    on_shutdown = shutdown
    functions = [
        task_label_state_by_id,
        task_label_transition_by_id,
        task_label_graph,
    ]
    cron_jobs = [
        cron(
            cron_poll_unlabeled_data,
            hour=CRON_HOURS,
            minute=CRON_MINUTES,
        )
    ]
    redis_settings = redis_settings
