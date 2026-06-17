import logging

from src.core.neo import neo_manager
from src.repositories.labeling_repo import LabelingRepository
from src.services.labeling.rule_based import (
    label_crawler_state,
    label_crawler_transition,
)

logger = logging.getLogger("arq.worker.labeling")


async def task_label_state_by_id(ctx: dict, state_id: str) -> dict:
    """Label one queued state and return it to pending if labeling fails."""
    logger.info(f"[State:{state_id}] Starting labeling task")

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        try:
            state = await repo.get_single_state(state_id)
            await repo.save_labeled_state(label_crawler_state(state))
        except Exception:
            logger.exception(
                f"[State:{state_id}] Labeling failed; reverting to PENDING"
            )
            await repo.set_state_pending(state_id)
            raise

    logger.info(f"[State:{state_id}] Successfully labeled and saved")
    return {"status": "success", "state_id": state_id}


async def task_label_transition_by_id(ctx: dict, transition_id: str) -> dict:
    """Label one queued transition and return it to pending on failure."""
    logger.info(f"[Transition:{transition_id}] Starting labeling task")

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        try:
            transition = await repo.get_single_transition(transition_id)
            from_state = await repo.get_single_state(transition.from_state_id)
            labeled = await label_crawler_transition(transition, from_state)
            await repo.save_labeled_transition(labeled)
        except Exception:
            logger.exception(
                f"[Transition:{transition_id}] Labeling failed; "
                "reverting to PENDING"
            )
            await repo.set_transition_pending(transition_id)
            raise

    logger.info(f"[Transition:{transition_id}] Successfully labeled and saved")
    return {"status": "success", "transition_id": transition_id}


async def task_label_graph(ctx: dict, session_id: str) -> dict:
    """Label queued records in a session with per-item failure isolation.

    Each successful item is saved immediately as ``COMPLETED``. An exception
    returns only the affected item to ``PENDING`` and processing continues with
    the remainder of the session.
    """
    logger.info(f"[Graph:{session_id}] Starting incremental graph labeling")
    completed_states = 0
    completed_transitions = 0
    failed_states: list[str] = []
    failed_transitions: list[str] = []

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        graph = await repo.get_graph(session_id)
        if graph is None:
            return {"status": "empty", "graph_session_id": session_id}

        for state_id, state in graph.states.items():
            if state_id in graph.skip_states:
                continue
            try:
                await repo.save_labeled_state(label_crawler_state(state))
                completed_states += 1
            except Exception:
                failed_states.append(state_id)
                logger.exception(f"[State:{state_id}] Labeling failed")
                await repo.set_state_pending(state_id)

        for transition in graph.transitions:
            try:
                from_state = graph.states.get(transition.from_state_id)
                if from_state is None:
                    raise ValueError(
                        f"Origin state {transition.from_state_id} is unavailable"
                    )
                labeled = await label_crawler_transition(transition, from_state)
                await repo.save_labeled_transition(labeled)
                completed_transitions += 1
            except Exception:
                failed_transitions.append(transition.id)
                logger.exception(f"[Transition:{transition.id}] Labeling failed")
                await repo.set_transition_pending(transition.id)

    status = "success"
    if failed_states or failed_transitions:
        status = "partial_failure"

    logger.info(
        f"[Graph:{session_id}] Finished: {completed_states} states, "
        f"{completed_transitions} transitions, "
        f"{len(failed_states) + len(failed_transitions)} failures"
    )
    return {
        "status": status,
        "graph_session_id": session_id,
        "completed_states": completed_states,
        "completed_transitions": completed_transitions,
        "failed_state_ids": failed_states,
        "failed_transition_ids": failed_transitions,
    }
