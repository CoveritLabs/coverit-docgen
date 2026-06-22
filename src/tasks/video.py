import logging
import uuid
from pathlib import Path

from arq import Retry

from src.core.config import get_settings
from src.core.neo import neo_manager
from src.models.bdd import BddGenerationInput
from src.repositories.bdd_repo import BddRepository
from src.repositories.video_repo import VideoRepository
from src.services.video.config import get_video_render_config
from src.services.video.generator import VideoGenerator

settings = get_settings()
logger = logging.getLogger("arq.worker.video")


async def task_generate_video(ctx: dict, payload: dict) -> dict:
    """Generate an MP4 walkthrough for one or more recorded flows."""

    request = BddGenerationInput.model_validate(payload)
    async with neo_manager.driver.session() as session:
        flows = await VideoRepository(session).resolve_flows(
            request.session_id,
            request.flows,
        )

    output_dir = Path(settings.video_output_dir)
    result = await VideoGenerator(get_video_render_config()).generate(
        request.session_id,
        flows,
        output_dir,
    )
    logger.info(
        f"[Video:{request.session_id}] Generated MP4 artifact at {result.artifact_path}"
    )
    return result.model_dump()
