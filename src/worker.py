# worker.py
from src.core.redis import redis_settings
from src.core.database import session_manager
from src.core.neo import neo_manager
from src.tasks.labeling import task_label_state, task_label_transition, task_label_graph


async def startup(ctx: dict) -> None:
    """
    Lifecycle hook triggered when the ARQ worker boots up.
    Initializes the database connection pool so tasks can save to Postgres.
    """
    await session_manager.init()
    neo_manager.init()
    print("Worker initialized database connection.")


async def shutdown(ctx: dict) -> None:
    """
    Lifecycle hook triggered when the ARQ worker shuts down.
    Gracefully closes the database connection pool.
    """
    await session_manager.close()
    await neo_manager.close()
    print("Worker closed database connection.")


class WorkerSettings:
    """Configuration class for the ARQ worker."""

    # Hooks to run on startup/shutdown
    on_startup = startup
    on_shutdown = shutdown

    # Register the background functions
    functions = [task_label_state, task_label_transition, task_label_graph]

    # Connect to Redis
    redis_settings = redis_settings
