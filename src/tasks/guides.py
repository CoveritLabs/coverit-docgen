import logging
import uuid

from arq import Retry

from src.core.config import get_settings
from src.core.neo import neo_manager
from src.models.guides import UserGuideInput, UserGuideResult
from src.repositories.bdd_repo import BddRepository
from src.repositories.guide_repo import GuideRepository
from src.services.guides.formatter import format_user_guide

settings = get_settings()
logger = logging.getLogger("arq.worker.guides")


async def task_generate_user_guide(ctx: dict, payload: dict) -> dict:
    """Generate a clear user guide for the shortest path between two states."""
    request = UserGuideInput.model_validate(payload)
    session_id = request.session_id
    job_try = int(ctx.get("job_try", 1))

    async with neo_manager.driver.session() as session:
        bdd_repo = BddRepository(session)
        status = await bdd_repo.get_labeling_status(session_id)
        if status["state_count"] == 0:
            raise ValueError(f"Session {session_id} contains no states")

        invalid = status["invalid_states"] + status["invalid_transitions"]
        if invalid:
            raise ValueError(
                f"Session {session_id} contains {invalid} invalid labeling statuses"
            )

        pending = status["pending_states"] + status["pending_transitions"]
        queued = status["queued_states"] + status["queued_transitions"]
        if pending or queued:
            logger.info(
                f"[Guide:{session_id}] Incomplete labeling detected. "
                f"States (Pending: {status['pending_states']}, "
                f"Queued: {status['queued_states']}) | "
                f"Transitions (Pending: {status['pending_transitions']}, "
                f"Queued: {status['queued_transitions']})"
            )
            if job_try >= settings.bdd_max_retries:
                raise RuntimeError(
                    f"Labeling did not complete for session {session_id} "
                    f"after {job_try} attempts"
                )

            if pending:
                claim = await bdd_repo.claim_unlabeled(session_id, uuid.uuid4().hex)
                state_ids = claim.get("state_ids") or []
                transition_ids = claim.get("transition_ids") or []
                if state_ids or transition_ids:
                    try:
                        job = await ctx["redis"].enqueue_job(
                            "task_label_graph",
                            session_id,
                        )
                        if job is None:
                            raise RuntimeError("ARQ did not enqueue the labeling job")
                    except Exception:
                        logger.error(f"Labeling session {session_id} failed")
                        await bdd_repo.rollback_claim(
                            session_id,
                            state_ids,
                            transition_ids,
                        )
                        raise

            logger.info(
                f"[Guide:{session_id}] Waiting for labeling completion "
                f"on attempt {job_try}"
            )
            raise Retry(defer=settings.bdd_retry_delay_seconds)

        path = await GuideRepository(session).resolve_shortest_path(
            session_id,
            request.start_state_hash,
            request.end_state_hash,
        )

    guide = format_user_guide(path)
    result = UserGuideResult(
        status="success",
        session_id=session_id,
        start_state_hash=request.start_state_hash,
        end_state_hash=request.end_state_hash,
        guide=guide,
        step_count=len(path.transitions),
    )
    print(result.guide)
    logger.info(
        f"[Guide:{session_id}] Generated user guide with {len(path.transitions)} steps"
    )
    return result.model_dump()
