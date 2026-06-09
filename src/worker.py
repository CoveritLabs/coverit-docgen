# worker.py
from src.core.redis import redis_settings
from src.core.config import get_settings
from src.core.database import session_manager
from src.tasks.labeling import task_label_state, task_label_transition


async def startup(ctx: dict) -> None:
    """
    Lifecycle hook triggered when the ARQ worker boots up.
    Initializes the database connection pool so tasks can save to Postgres.
    """
    settings = get_settings()
    await session_manager.init(settings.database_url)
    print("Worker initialized database connection.")


async def shutdown(ctx: dict) -> None:
    """
    Lifecycle hook triggered when the ARQ worker shuts down.
    Gracefully closes the database connection pool.
    """
    await session_manager.close()
    print("Worker closed database connection.")


class WorkerSettings:
    """Configuration class for the ARQ worker."""

    # Hooks to run on startup/shutdown
    on_startup = startup
    on_shutdown = shutdown

    # Register the background functions
    functions = [task_label_state, task_label_transition]

    # Connect to Redis
    redis_settings = redis_settings
