import logging
from src.core.neo import neo_manager
from src.models.queries import GET_UNLABELED_STATES, GET_UNLABELED_TRANSITIONS

logger = logging.getLogger("arq.poller")

async def cron_poll_unlabeled_data(ctx: dict):
    """
    Cron job that polls Neo4j for unlabeled data and enqueues them for processing.
    """
    logger.info("Starting scheduled poll for unlabeled Neo4j data...")
    redis = ctx['redis']
    
    if not neo_manager.driver:
        logger.error("Database connection unavailable. Skipping poll.")
        return

    async with neo_manager.driver.session() as session:
        state_result = await session.run(GET_UNLABELED_STATES)
        states = await state_result.data()
        
        for record in states:
            state_id = record["id"]
            await redis.enqueue_job('task_label_state_by_id', state_id)
            logger.info(f"Enqueued state {state_id} for labeling.")

        transition_result = await session.run(GET_UNLABELED_TRANSITIONS)
        transitions = await transition_result.data()
        
        for record in transitions:
            trans_id = record["id"]
            await redis.enqueue_job('task_label_transition_by_id', trans_id)
            logger.info(f"Enqueued transition {trans_id} for labeling.")
            
    logger.info(f"Cron poll complete. Queued {len(states)} states and {len(transitions)} transitions.")