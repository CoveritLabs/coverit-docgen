from fastapi import HTTPException, status
from src.core.redis import redis_manager
from src.models.graph import CrawlerState, CrawlerTransition


class LabelingService:
    """
    Service responsible for handling incoming crawler data and orchestrating
    the asynchronous labeling processes via Redis ARQ.
    """

    async def enqueue_state_labeling(self, state: CrawlerState) -> str:
        """
        Pushes a job to the Redis queue to label a single CrawlerState.

        Args:
            state (CrawlerState): The raw state from the Crawler.

        Returns:
            str: The ARQ Job ID.
        """
        if not redis_manager.pool:
            raise HTTPException(status_code=500, detail="Redis pool not initialized")

        # We dump to dict because ARQ needs native Python types for serialization
        job = await redis_manager.pool.enqueue_job(
            "task_label_state", state.model_dump()
        )
        return job.job_id

    async def enqueue_transition_labeling(self, transition: CrawlerTransition) -> str:
        """
        Pushes a job to the Redis queue to label a CrawlerTransition.
        """
        if not redis_manager.pool:
            raise HTTPException(status_code=500, detail="Redis pool not initialized")

        job = await redis_manager.pool.enqueue_job(
            "task_label_transition", transition.model_dump()
        )
        return job.job_id
