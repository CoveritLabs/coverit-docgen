import logging
import uuid

from arq import Retry

from src.core.config import get_settings
from src.core.neo import neo_manager
from src.models.bdd import BddGenerationInput
from src.repositories.bdd_repo import BddRepository
from src.services.bdd.regression import compile_bdd

settings = get_settings()
logger = logging.getLogger("arq.worker.bdd")


async def task_generate_bdd(ctx: dict, payload: dict) -> dict:
    """Generate BDD artifacts after all graph records are labeled."""
    request = BddGenerationInput.model_validate(payload)
    session_id = request.session_id
    job_try = int(ctx.get("job_try", 1))

    async with neo_manager.driver.session() as session:
        repo = BddRepository(session)
        status = await repo.get_labeling_status(session_id)
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
            if job_try >= settings.bdd_max_retries:
                raise RuntimeError(
                    f"Labeling did not complete for session {session_id} "
                    f"after {job_try} attempts"
                )

            if pending:
                claim = await repo.claim_unlabeled(
                    session_id,
                    uuid.uuid4().hex,
                )
                state_ids = claim.get("state_ids") or []
                transition_ids = claim.get("transition_ids") or []
                if state_ids or transition_ids:
                    try:
                        job = await ctx["redis"].enqueue_job(
                            "task_label_graph",
                            session_id,
                        )
                        if job is None:
                            raise RuntimeError(
                                "ARQ did not enqueue the labeling job"
                            )
                    except Exception:
                        logger.error(f"Labeling session {session_id} Failed")
                        await repo.rollback_claim(
                            session_id,
                            state_ids,
                            transition_ids,
                        )
                        raise

            logger.info(
                "[BDD:%s] Waiting for labeling completion on attempt %s",
                session_id,
                job_try,
            )
            raise Retry(defer=settings.bdd_retry_delay_seconds)

        flows = await repo.resolve_flows(session_id, request.flows)
        state_hashes = list(
            dict.fromkeys(
                state.state_hash
                for flow in flows
                for transition in flow.transitions
                for state in (transition.from_state, transition.to_state)
            )
        )
        outgoing_locators = await repo.get_outgoing_locators(
            session_id,
            state_hashes,
        )

    compiled = compile_bdd(flows, outgoing_locators)
    logger.info(
        "[BDD:%s] Generated feature '%s' with %s scenarios",
        session_id,
        compiled.feature_name,
        len(flows),
    )
    return {
        "status": "success",
        "session_id": session_id,
        "feature_name": compiled.feature_name,
        "feature_text": compiled.feature_text,
        "states": compiled.states,
        "transitions": compiled.transitions,
        "assertions": {},
        "action_hooks": {},
    }
