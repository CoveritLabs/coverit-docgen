import logging
from fastapi import APIRouter, Depends, status, HTTPException
from src.models.queries import *
from src.schemas.crawler import (
    LabelStateRequest,
    LabelTransitionRequest,
    LabelGraphRequest,
)
from src.services.labeling.labeling_service import LabelingService
from src.repositories.labeling_repo import LabelingRepository
from src.core.neo import neo_manager

logger = logging.getLogger(__name__)
api_router = APIRouter(tags=["Labeling"])


def get_labeling_service() -> LabelingService:
    """Dependency injection for the Labeling Service."""
    return LabelingService()


@api_router.get("/", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check():
    """
    Base health check endpoint to verify the service is live and reachable.
    """
    logger.debug("Health check ping received.")
    return {"status": "healthy", "service": "docgen-api"}


@api_router.post("/label/state", status_code=status.HTTP_202_ACCEPTED)
async def trigger_state_labeling(
    request: LabelStateRequest, service: LabelingService = Depends(get_labeling_service)
):
    """
    Retrieves a CrawlerState from Neo4j using the provided ID and queues it for background labeling.
    """
    logger.info(f"Triggering state labeling for state_id: {request.id}")

    if not neo_manager.driver:
        logger.error(
            f"Failed to queue state labeling for state_id: {request.id}. Database connection unavailable."
        )
        raise HTTPException(status_code=503, detail="Database connection unavailable")

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        crawler_state = await repo.get_single_state(request.id)

    job_id = await service.enqueue_state_labeling(crawler_state)
    logger.info(
        f"Successfully queued state labeling for state_id: {request.id} | job_id: {job_id}"
    )

    return {"message": "State labeling queued successfully", "job_id": job_id}


@api_router.post("/label/transition", status_code=status.HTTP_202_ACCEPTED)
async def trigger_transition_labeling(
    request: LabelTransitionRequest,
    service: LabelingService = Depends(get_labeling_service),
):
    """
    Retrieves a CrawlerTransition from Neo4j using the transition ID
    and queues it for background labeling.
    """
    logger.info(f"Triggering transition labeling for transition_id: {request.id}")

    if not neo_manager.driver:
        logger.error(
            f"Failed to queue transition labeling for transition_id: {request.id}. Database connection unavailable."
        )
        raise HTTPException(status_code=503, detail="Database connection unavailable")

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        crawler_transition = await repo.get_single_transition(request.id)

    job_id = await service.enqueue_transition_labeling(crawler_transition)
    logger.info(
        f"Successfully queued transition labeling for transition_id: {request.id} | job_id: {job_id}"
    )

    return {"message": "Transition labeling queued successfully", "job_id": job_id}


@api_router.post("/label/graph", status_code=status.HTTP_202_ACCEPTED)
async def trigger_graph_labeling(
    request: LabelGraphRequest,
    service: LabelingService = Depends(get_labeling_service),
):
    """
    Retrieves all States and Transitions for a given session_id from Neo4j
    and queues the complete CrawlerGraph for background labeling.
    """
    logger.info(f"Triggering graph labeling for session_id: {request.session_id}")

    if not neo_manager.driver:
        logger.error(
            f"Failed to queue graph labeling for session_id: {request.session_id}. Database connection unavailable."
        )
        raise HTTPException(status_code=503, detail="Database connection unavailable")

    async with neo_manager.driver.session() as session:
        repo = LabelingRepository(session)
        crawler_graph = await repo.get_graph(request.session_id)

    job_id = await service.enqueue_graph_labeling(crawler_graph)
    logger.info(
        f"Successfully queued graph labeling for session_id: {request.session_id} | job_id: {job_id}"
    )

    return {"message": "Graph labeling queued successfully", "job_id": job_id}
