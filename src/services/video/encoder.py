import shutil
import subprocess
from pathlib import Path


class FfmpegEncoder:
    def __init__(self, ffmpeg_path: str | None = None):
        self.ffmpeg_path = resolve_ffmpeg_path(ffmpeg_path)

    def encode(
        self,
        frame_paths: list[Path],
        fps: int,
        output_path: Path,
    ) -> None:
        if not frame_paths:
            raise ValueError("No frames were produced for video encoding")
        if not self.ffmpeg_path:
            raise RuntimeError(
                "ffmpeg is required to encode video output. Install ffmpeg, set "
                "FFMPEG_PATH to the ffmpeg executable, or install the "
                "imageio-ffmpeg Python package."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame_pattern = str(frame_paths[0].parent / "frame_%05d.png")

        # We feed PNGs at a fixed input framerate.  Using -framerate
        # (not -r) on the input side ensures ffmpeg treats the image
        # sequence as a constant-FPS stream -- this avoids jitter when
        # individual frames take slightly different times to decode.
        command = [
            self.ffmpeg_path,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            frame_pattern,
        ]

        # Encode with libx264 using the slow preset for the best
        # quality-per-bit.  CRF 18 is visually lossless for screen-
        # recording-style content.  The High profile + 8 ref frames
        # gives the encoder more motion vectors to work with, which
        # makes zooms and cursor motion noticeably smoother at the
        # same bitrate.  +faststart moves the moov atom to the front
        # so the MP4 can start playing immediately when streamed.
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "18",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-refs",
                "8",
                "-movflags",
                "+faststart",
                "-r",
                str(fps),
            ]
        )

        command.append(str(output_path))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")


def resolve_ffmpeg_path(ffmpeg_path: str | None = None) -> str | None:
    configured = ffmpeg_path or shutil.which("ffmpeg")
    if configured:
        return str(Path(configured).expanduser())

    try:
        import imageio_ffmpeg
    except ImportError:
        return None

    return imageio_ffmpeg.get_ffmpeg_exe()
