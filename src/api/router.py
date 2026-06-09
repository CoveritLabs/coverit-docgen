from fastapi import APIRouter, Depends, status
from src.models.graph import CrawlerState, CrawlerTransition
from src.services.labeling.labeling_service import LabelingService

api_router = APIRouter(tags=["Labeling"])


def get_labeling_service() -> LabelingService:
    """Dependency injection for the Labeling Service."""
    return LabelingService()


@api_router.get("/", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check():
    """
    Base health check endpoint to verify the service is live and reachable.
    """
    return {"status": "healthy", "service": "docgen-api"}


@api_router.post("/label/state", status_code=status.HTTP_202_ACCEPTED)
async def trigger_state_labeling(
    state: CrawlerState, service: LabelingService = Depends(get_labeling_service)
):
    """
    Receives a CrawlerState payload and queues it for background labeling.
    Returns HTTP 202 Accepted immediately with the background Job ID.
    """
    job_id = await service.enqueue_state_labeling(state)
    return {"message": "State labeling queued successfully", "job_id": job_id}


@api_router.post("/label/transition", status_code=status.HTTP_202_ACCEPTED)
async def trigger_transition_labeling(
    transition: CrawlerTransition,
    service: LabelingService = Depends(get_labeling_service),
):
    """
    Receives a CrawlerTransition payload (containing the pressed element)
    and queues it for background labeling.
    """
    job_id = await service.enqueue_transition_labeling(transition)
    return {"message": "Transition labeling queued successfully", "job_id": job_id}
