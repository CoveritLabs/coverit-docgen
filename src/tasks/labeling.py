# src/tasks/labeling.py
import logging
from src.models.graph import CrawlerState, CrawlerTransition
from src.services.labeling.rule_based import (
    label_crawler_state,
    label_crawler_transition,
)
from src.core.database import session_manager
from src.repositories.labeling_repo import LabelingRepository

logger = logging.getLogger(__name__)


async def task_label_state(ctx: dict, state_dict: dict) -> dict:
    """
    Background ARQ task to label a CrawlerState and save it to PostgreSQL.

    Args:
        ctx (dict): The ARQ context dictionary.
        state_dict (dict): The state data serialized as a dictionary.
    """
    state = CrawlerState.model_validate(state_dict)
    logger.info(f"Processing label task for state: {state.id}")

    labeled_state = label_crawler_state(state)

    async with session_manager.session() as session:
        repo = LabelingRepository(session)
        await repo.save_labeled_state(labeled_state)

    logger.info(f"Successfully labeled and saved state: {state.id}")
    return {"status": "success", "state_id": state.id}


async def task_label_transition(ctx: dict, transition_dict: dict) -> dict:
    """
    Background ARQ task to label a CrawlerTransition and save it to PostgreSQL.
    """
    transition = CrawlerTransition.model_validate(transition_dict)
    element_id = transition.pressed_element.id
    logger.info(f"Processing label task for transition element: {element_id}")

    labeled_element = label_crawler_transition(transition)

    async with session_manager.session() as session:
        repo = LabelingRepository(session)
        await repo.save_labeled_element(labeled_element)

    logger.info(f"Successfully labeled and saved element: {element_id}")
    return {"status": "success", "element_id": element_id}
