import logging
from src.services.labeling.rule_based import (
    label_crawler_state,
    label_crawler_transition,
    label_crawler_graph,
)
from src.core.neo import neo_manager
from src.repositories.labeling_repo import LabelingRepository
from src.models.queries import (
    SET_STATE_PENDING,
    SET_TRANSITION_PENDING,
    SET_SESSION_PENDING,
)

logger = logging.getLogger("arq.worker.labeling")


async def task_label_state_by_id(ctx: dict, state_id: str) -> dict:
    """
    Background ARQ task to label a CrawlerState.

    Fetches the state by its Neo4j element ID, extracts the labeling data,
    and saves the result back to the database. If the process fails,
    the state's labeling_status is reverted to 'PENDING' for the cron job to retry.

    Args:
        ctx (dict): The ARQ context dictionary.
        state_id (str): The elementId of the state in Neo4j.
    """
    logger.info(f"[State:{state_id}] Starting labeling task...")

    async with neo_manager.driver.session() as session:
        try:
            repo = LabelingRepository(session)

            state = await repo.get_single_state(state_id)

            if not state:
                raise ValueError(f"State with ID {state_id} not found in database.")

            labeled_state = label_crawler_state(state)

            await repo.save_labeled_state(labeled_state)

            logger.info(f"[State:{state_id}] Successfully labeled and saved.")
            return {"status": "success", "state_id": state_id}

        except Exception as e:
            logger.exception(
                f"[State:{state_id}] Error during labeling. Reverting status to PENDING."
            )

            try:
                result = await session.run(SET_STATE_PENDING, id=state_id)
                await result.consume()
            except Exception as rollback_err:
                logger.error(
                    f"[State:{state_id}] CRITICAL: Failed to revert status to PENDING: {rollback_err}"
                )

            raise e


async def task_label_transition_by_id(ctx: dict, transition_id: str) -> dict:
    """
    Background ARQ task to label a CrawlerTransition.

    Uses Playwright to visually label a transition based on its origin state.
    If it fails, it rolls the transition's labeling_status back to 'PENDING'.
    """
    logger.info(f"[Transition:{transition_id}] Starting labeling task...")

    async with neo_manager.driver.session() as session:
        try:
            repo = LabelingRepository(session)

            transition = await repo.get_single_transition(transition_id)

            if not transition:
                raise ValueError(f"Transition with ID {transition_id} not found.")

            from_state = await repo.get_single_state(transition.from_state_id)

            if not from_state:
                raise ValueError(
                    f"Origin state {transition.from_state_id} not found for transition {transition_id}."
                )

            labeled_transition = label_crawler_transition(transition, from_state)

            await repo.save_labeled_transition(labeled_transition)

            logger.info(f"[Transition:{transition_id}] Successfully labeled and saved.")
            return {"status": "success", "transition_id": transition_id}

        except Exception as e:
            logger.exception(
                f"[Transition:{transition_id}] Error during labeling. Reverting status to PENDING."
            )

            try:
                result = await session.run(SET_TRANSITION_PENDING, id=transition_id)
                await result.consume()
            except Exception as rollback_err:
                logger.error(
                    f"[Transition:{transition_id}] CRITICAL: Failed to revert status to PENDING: {rollback_err}"
                )

            raise e


async def task_label_graph(ctx: dict, session_id: dict) -> dict:
    """
    Background ARQ task to label a complete CrawlerGraph.
    """
    logger.info(f"[Graph:{session_id}] Starting full graph labeling task...")

    async with neo_manager.driver.session() as session:
        try:
            repo = LabelingRepository(session)

            graph = await repo.get_graph(session_id)

            if not graph:
                logger.warning("[Graph:{session_id}] skipping graph labeling.")
                return {"status": "Not Completed", "graph_session_id": session_id}

            logger.info(
                f"[Graph:{session_id}] skipping {len(graph.skip_states)} states labeling."
            )

            labeled_graph = label_crawler_graph(graph)

            await repo.save_labeled_graph(labeled_graph)

            len_states = len(graph.states) - len(graph.skip_states)
            len_transitions = len(graph.transitions)

            logger.info(
                f"[Graph:{session_id}] Successfully labeled and saved graph. "
                f"States: {len_states}, Transitions: {len_transitions}"
            )
            return {"status": "success", "graph_session_id": session_id}

        except Exception as e:
            logger.exception(
                f"[Session:{session_id}] Failed labeling. Reverting QUEUED items to PENDING."
            )

            try:
                result = await session.run(SET_SESSION_PENDING, session_id=session_id)
                await result.consume()
            except Exception as rollback_err:
                logger.error(
                    f"[Session:{session_id}] CRITICAL: Failed to revert status to PENDING: {rollback_err}"
                )

            raise e
