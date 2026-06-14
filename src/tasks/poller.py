import logging
from src.core.neo import neo_manager
from src.models.queries import GET_UNLABELED_SESSIONS

logger = logging.getLogger("arq.poller")

MAX_SESSIONS_PER_POLL = 100


async def cron_poll_unlabeled_data(ctx: dict):
    """
    Cron job that polls Neo4j for unlabeled data and enqueues them for processing.
    """
    logger.info("Starting scheduled poll for unlabeled Neo4j data...")
    redis = ctx["redis"]

    if not neo_manager.driver:
        logger.error("Database connection unavailable. Skipping poll.")
        return

    async with neo_manager.driver.session() as session:
        result = await session.run(GET_UNLABELED_SESSIONS)
        records = await result.data()

        unique_sessions = {
            record["id"] for record in records if record.get("id") is not None
        }

        if len(unique_sessions) > MAX_SESSIONS_PER_POLL:
            logger.warning(
                f"Found {len(unique_sessions)} sessions, "
                f"exceeds limit ({MAX_SESSIONS_PER_POLL}). Skipping poll."
            )
            return

        queued = 0
        for session_id in unique_sessions:
            await redis.enqueue_job("task_label_graph", session_id)
            queued += 1
            logger.info(f"Enqueued session {session_id} for full graph labeling.")

    logger.info(f"Cron poll complete. Queued {queued} unique sessions.")
