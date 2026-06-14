import logging
from src.models.graph import CrawlerState, CrawlerTransition, CrawlerGraph
from src.services.labeling.rule_based import (
    label_crawler_state,
    label_crawler_transition,
    label_crawler_graph,
)
from src.core.neo import neo_manager
from src.repositories.labeling_repo import LabelingRepository

logger = logging.getLogger(__name__)


async def task_label_state(ctx: dict, state_dict: dict) -> dict:
    """
    Background ARQ task to label a CrawlerState and save it to Neo4j.

    Args:
        ctx (dict): The ARQ context dictionary.
        state_dict (dict): The state data serialized as a dictionary.
    """
    state = CrawlerState.model_validate(state_dict)
    logger.info(f"Processing label task for state: {state.id}")

    labeled_state = label_crawler_state(state)

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        await repo.save_labeled_state(labeled_state)

    logger.info(f"Successfully labeled and saved state: {state.id}")
    return {"status": "success", "state_id": state.id}


async def task_label_transition(ctx: dict, transition_dict: dict) -> dict:
    """
    Background ARQ task to label a CrawlerTransition and save it to Neo4j.
    """
    transition = CrawlerTransition.model_validate(transition_dict)
    logger.info(f"Processing label task for transition: {transition.id}")

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        from_state = repo.get_single_state(transition.from_state_id)
        labeled_element = label_crawler_transition(transition, from_state)
        await repo.save_labeled_transition(labeled_element)

    logger.info(f"Successfully labeled and saved transition: {transition.id}")
    return {"status": "success", "transition_id": transition.id}


async def task_label_graph(ctx: dict, graph_dict: dict) -> dict:
    """
    Background ARQ task to label a CrawlerGraph and save it to Neo4j.
    """
    graph = CrawlerGraph.model_validate(graph_dict)
    logger.info(f"Processing label task for graph with session: {graph.session_id}")

    labeled_graph = label_crawler_graph(graph)

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        await repo.save_labeled_graph(labeled_graph)

    logger.info(f"Successfully labeled and saved graph: {graph.session_id}")
    return {"status": "success", "graph_session_id": graph.session_id}
