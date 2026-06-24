from dataclasses import dataclass
from typing import Tuple

from src.core.config import get_settings


@dataclass(frozen=True)
class VideoRenderConfig:
    # Output video width in pixels.
    width: int
    # Output video height in pixels.
    height: int
    # Output video frame rate.
    fps: int
    # Global speed multiplier for generated motion and typing phases.
    action_speed: float
    # Seed used for deterministic typing cadence.
    random_seed: int
    # Fraction of the output frame occupied by the browser card at rest.
    window_scale: float = 0.86
    # Corner radius for the browser card while it is zoomed out.
    window_corner_radius: int = 14
    # Solid background color behind the browser card.
    window_background_color: Tuple[int, int, int] = (245, 245, 245)
    # Vertical offset for the browser card's primary shadow.
    window_shadow_offset_y: int = 8
    # Blur radius for the browser card's primary shadow.
    window_shadow_blur: float = 30.0
    # Opacity for the browser card's primary shadow.
    window_shadow_opacity: float = 0.22
    # Blur radius for the wider ambient browser card halo.
    window_shadow_halo_blur: float = 60.0
    # Opacity for the wider ambient browser card halo.
    window_shadow_halo_opacity: float = 0.08
    # Maximum zoom level used when focusing on a target element.
    window_focus_zoom: float = 1.4
    # Seconds to hold the browser card at rest before zooming in.
    phase_rest_intro: float = 0.20
    # Seconds spent zooming from the rest card to the focused target.
    phase_zoom_in: float = 0.50
    # Seconds spent moving the cursor to the target.
    phase_cursor_move: float = 0.55
    # Seconds to hold at full focus after the action has settled.
    phase_action_hold: float = 0.15
    # Seconds spent zooming from the focused target back to rest.
    phase_zoom_out: float = 0.65
    # Seconds to hold the browser card at rest after zooming out.
    phase_rest_outro: float = 0.20
    # Seconds spent panning between nearby targets while staying zoomed in.
    phase_focus_pan: float = 0.35
    # Enables skipping zoom-out/zoom-in cycles for nearby consecutive targets.
    camera_sticky_enabled: bool = True
    # Maximum document-space center distance for sticky focused panning.
    camera_sticky_max_distance_px: float = 520.0
    # Maximum per-axis distance as a fraction of the focused crop size.
    camera_sticky_max_axis_ratio: float = 0.55
    # Number of frames used for the cursor press feedback.
    click_press_frames: int = 5
    # Smallest cursor scale during click press feedback.
    click_press_scale_min: float = 0.72
    # Strength for any focus dimming around the target.
    focus_dim_strength: float = 0.16
    # Blur radius for any focus dimming around the target.
    focus_blur_radius: float = 3.0
    # Padding around the target when computing the focused crop.
    focus_padding: float = 18.0


def get_video_render_config() -> VideoRenderConfig:
    settings = get_settings()
    return VideoRenderConfig(
        width=settings.video_default_width,
        height=settings.video_default_height,
        fps=settings.video_default_fps,
        action_speed=settings.video_action_speed,
        random_seed=settings.video_random_seed,
        window_scale=settings.video_window_scale,
    )
