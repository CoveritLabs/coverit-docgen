import logging
import uuid

from src.core.config import get_settings
from src.core.neo import neo_manager
from src.models.queries import CLAIM_UNLABELED_SESSIONS
from src.repositories.labeling_repo import LabelingRepository

settings = get_settings()
logger = logging.getLogger("arq.poller")


async def cron_poll_unlabeled_data(ctx: dict) -> None:
    """Atomically claim pending graph records and enqueue one job per session.

    Neo4j changes eligible ``NULL``/``PENDING`` records to ``QUEUED`` before
    this function dispatches ARQ jobs. If dispatch fails or ARQ rejects a
    duplicate job, exactly the IDs claimed by this poll are returned to
    ``PENDING`` for a later retry.
    """
    logger.info("Starting scheduled poll for unlabeled Neo4j data")
    redis = ctx["redis"]

    if not neo_manager.driver:
        logger.error("Neo4j connection unavailable; skipping poll")
        return

    queued = 0
    async with neo_manager.driver.session() as session:
        result = await session.run(
            CLAIM_UNLABELED_SESSIONS,
            limit=settings.max_sessions_per_poll,
            claim_id=uuid.uuid4().hex,
        )
        claims = await result.data()
        repo = LabelingRepository(session)

        for claim in claims:
            session_id = claim["id"]
            state_ids = claim.get("state_ids") or []
            transition_ids = claim.get("transition_ids") or []
            try:
                job = await redis.enqueue_job("task_label_graph", session_id)
                if job is None:
                    raise RuntimeError("ARQ did not enqueue the session job")
            except Exception:
                logger.exception(
                    f"Failed to enqueue session {session_id}; "
                    "rolling back its claim"
                )
                await repo.rollback_claim(
                    session_id,
                    state_ids,
                    transition_ids,
                )
                continue

            queued += 1
            logger.info(
                f"Enqueued session {session_id} with {len(state_ids)} "
                f"states and {len(transition_ids)} transitions"
            )

    logger.info(f"Cron poll complete; queued {queued} sessions")
