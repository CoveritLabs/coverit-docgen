import logging
from arq import cron
from src.core.redis import redis_settings
from src.core.database import session_manager
from src.core.neo import neo_manager
from src.core.config import get_settings
from src.utils.helpers import parse_cron_string
from src.tasks.labeling import (
    task_label_state_by_id,
    task_label_transition_by_id,
    task_label_graph,
)
from src.tasks.poller import cron_poll_unlabeled_data

logger = logging.getLogger("arq.worker")

settings = get_settings()

CRON_HOURS = parse_cron_string(settings.poller_cron_hours)
CRON_MINUTES = parse_cron_string(settings.poller_cron_minutes)


async def startup(ctx: dict) -> None:
    """
    Lifecycle hook triggered when the ARQ worker boots up.
    Initializes the database connection pool so tasks can save to Postgres.
    """
    await session_manager.init()
    neo_manager.init()
    logger.info("Worker initialized database connection.")
    logger.info("Triggering initial run immediately on startup...")
    await cron_poll_unlabeled_data(ctx)

async def shutdown(ctx: dict) -> None:
    """
    Lifecycle hook triggered when the ARQ worker shuts down.
    Gracefully closes the database connection pool.
    """
    await session_manager.close()
    await neo_manager.close()
    logger.info("Worker closed database connection.")


class WorkerSettings:
    """Configuration class for the ARQ worker."""

    # Hooks to run on startup/shutdown
    on_startup = startup
    on_shutdown = shutdown

    # Register the functions that actually do the heavy lifting
    functions = [task_label_state_by_id, task_label_transition_by_id, task_label_graph]

    # Register the CRON jobs to trigger the polling automatically
    cron_jobs = [cron(cron_poll_unlabeled_data, hour=CRON_HOURS, minute=CRON_MINUTES)]

    redis_settings = redis_settings
