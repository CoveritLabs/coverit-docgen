from dataclasses import dataclass
from typing import Tuple

from src.core.config import get_settings


@dataclass(frozen=True)
class VideoRenderConfig:
    width: int
    height: int
    fps: int
    action_speed: float
    random_seed: int
    # --- Window presentation (matches the reference video look) ---
    # When the camera is "zoomed out", the captured page sits as a small
    # floating card on a solid background.  ``window_scale`` is the
    # fraction of the frame the card occupies at rest (~0.72 wide).
    window_scale: float = 0.72
    window_corner_radius: int = 14
    window_background_color: Tuple[int, int, int] = (245, 245, 245)
    window_shadow_offset_y: int = 8
    window_shadow_blur: float = 30.0
    window_shadow_opacity: float = 0.22
    window_shadow_halo_blur: float = 60.0
    window_shadow_halo_opacity: float = 0.08
    # How far the card zooms in when focusing on a target.
    window_focus_zoom: float = 1.4
    # Per-phase timings (seconds).  These were tuned so the resulting
    # motion feels as smooth and "deliberate" as the reference video --
    # longer than the original which felt choppy.
    phase_rest_intro: float = 0.20
    phase_zoom_in: float = 0.50
    phase_cursor_move: float = 0.55
    phase_action_hold: float = 0.15
    phase_zoom_out: float = 0.65
    phase_rest_outro: float = 0.20
    # Click "press" feedback (a quick scale-down of the cursor).
    click_press_frames: int = 3
    # Soft dim applied to the area outside the focus ring while zoomed
    # in.  Keeps the original "spotlight" cue without overpowering the
    # new windowed look.
    focus_dim_strength: float = 0.16
    focus_blur_radius: float = 3.0
    focus_padding: float = 18.0


def get_video_render_config() -> VideoRenderConfig:
    settings = get_settings()
    return VideoRenderConfig(
        width=settings.video_default_width,
        height=settings.video_default_height,
        fps=settings.video_default_fps,
        action_speed=settings.video_action_speed,
        random_seed=settings.video_random_seed,
    )
