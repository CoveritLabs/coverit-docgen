import tempfile
from pathlib import Path

from src.models.video import (
    VideoGenerationResult,
    VideoResolvedFlow,
)
from src.services.video.config import VideoRenderConfig
from src.services.video.encoder import FfmpegEncoder
from src.services.video.renderer import BrowserFrameRenderer
from src.services.video.timeline import build_timelines


class VideoGenerator:
    """Orchestrates timeline expansion, rendering, audio, and MP4 encoding."""

    def __init__(self, config: VideoRenderConfig):
        self.config = config

    async def generate(
        self,
        session_id: str,
        flows: list[VideoResolvedFlow],
        output_dir: Path,
    ) -> VideoGenerationResult:
        timelines = build_timelines(flows)
        if not timelines or not any(timeline.shots for timeline in timelines):
            raise ValueError("No video shots were produced from the requested flows")

        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / f"{session_id}-video.mp4"

        with tempfile.TemporaryDirectory(prefix="coverit-video-") as temp:
            frame_dir = Path(temp) / "frames"
            render_output = await BrowserFrameRenderer(self.config).render(
                timelines,
                frame_dir,
            )

            FfmpegEncoder().encode(
                render_output.frame_paths,
                self.config.fps,
                artifact_path
            )

        return VideoGenerationResult(
            status="success",
            session_id=session_id,
            artifact_path=str(artifact_path),
            duration_seconds=round(render_output.duration_seconds, 3),
            resolution=f"{self.config.width}x{self.config.height}",
            fps=self.config.fps,
            flow_count=len(flows),
        )