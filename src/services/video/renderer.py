from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.core.playwright import playwright_manager
from src.services.video.config import VideoRenderConfig
from src.services.video.cursor import load_cursor_image
from src.services.video.effects import (
    Point,
    Rect,
    WindowParams,
    curved_cursor_path,
    screen_point_for_cursor,
    window_transform_for_progress,
)
from src.services.video.timeline import VideoFlowTimeline, VideoShot
from src.services.video.typing import typing_frames


@dataclass(frozen=True)
class CapturedScene:
    image: object
    target: Rect


@dataclass(frozen=True)
class RenderOutput:
    frame_paths: list[Path]
    duration_seconds: float


class BrowserFrameRenderer:
    """Renders browser interactions as a sequence of PNG frames.

    The renderer presents the captured page as a small floating
    "window" (with rounded corners and a soft drop shadow) centred on
    a solid background, exactly like the reference video.  For each
    shot the window smoothly zooms in to focus on the target element,
    the cursor glides along a curved path to that element, the action
    is performed, the window holds for a moment, and then smoothly
    zooms back out to the resting windowed state.  All motion uses
    higher-order easing (smootherstep / cubic-bezier) so transitions
    feel buttery instead of mechanical.
    """

    def __init__(self, config: VideoRenderConfig):
        self.config = config
        self.cursor_image, self.cursor_hotspot = load_cursor_image()
        self._window_params = self._build_window_params()

    async def render(
        self,
        timelines: list[VideoFlowTimeline],
        frame_dir: Path,
    ) -> RenderOutput:
        if playwright_manager._browser is None:
            raise RuntimeError("Playwright browser not started. Call start() first.")

        from PIL import Image

        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_paths: list[Path] = []
        # Cursor lives in *screenshot* coordinates (page space).
        previous_cursor = Point(self.config.width * 0.12, self.config.height * 0.85)
        elapsed_frames = 0

        for timeline in timelines:
            if not timeline.start_url.strip():
                raise ValueError("Video flow start URL is empty")

            page = await playwright_manager._browser.new_page(
                viewport={"width": self.config.width, "height": self.config.height}
            )
            try:
                try:
                    await page.goto(
                        timeline.start_url, wait_until="load", timeout=30000
                    )
                    await self._wait_for_page_stability(page)
                except Exception as exc:
                    raise ValueError(
                        f"Unable to open video flow start URL {timeline.start_url!r}"
                    ) from exc

                for shot_index, shot in enumerate(timeline.shots):
                    scene = await self._capture_scene(page, shot)
                    target_center = scene.target.center

                    shot_frames: list[Image.Image] = []

                    # 1. Rest intro -- window sits at rest, cursor visible.
                    shot_frames.extend(
                        self._rest_frames(
                            scene.image,
                            scene.target,
                            previous_cursor,
                            intro=True,
                        )
                    )

                    # 2. Zoom in -- window grows from rest to focused on target.
                    shot_frames.extend(
                        self._zoom_frames(
                            scene.image,
                            scene.target,
                            previous_cursor,
                            zoom_in=True,
                        )
                    )

                    # 3. Cursor move -- cursor glides from previous to target.
                    shot_frames.extend(
                        self._cursor_frames(
                            scene.image,
                            scene.target,
                            previous_cursor,
                            target_center,
                        )
                    )

                    # 4. Action -- typing or click, plus optional hold.
                    if shot.has_typing:
                        action_frames = await self._perform_typing_action(
                            page,
                            shot,
                            scene.target,
                            target_center,
                            shot_index,
                        )
                        shot_frames.extend(action_frames)
                        release_image = await self._capture_page(page)
                    else:
                        await self._perform_non_typing_action(page, shot)
                        release_image = await self._capture_page(page)
                        # Small "press" feedback frames using the release image.
                        shot_frames.extend(
                            self._press_frames(
                                release_image,
                                scene.target,
                                target_center,
                            )
                        )

                    # 5. Brief hold at full zoom after the action settles.
                    shot_frames.extend(
                        self._hold_frames(release_image, scene.target, target_center)
                    )

                    # 6. Zoom out -- window shrinks back to the resting state.
                    shot_frames.extend(
                        self._zoom_frames(
                            release_image,
                            scene.target,
                            target_center,
                            zoom_in=False,
                        )
                    )

                    # 7. Rest outro -- window at rest before next shot.
                    shot_frames.extend(
                        self._rest_frames(
                            release_image,
                            scene.target,
                            target_center,
                            intro=False,
                        )
                    )

                    for frame in shot_frames:
                        elapsed_frames += 1
                        path = frame_dir / f"frame_{elapsed_frames:05d}.png"
                        frame.save(path)
                        frame_paths.append(path)

                    previous_cursor = target_center
            finally:
                await page.close()

        return RenderOutput(
            frame_paths=frame_paths,
            duration_seconds=elapsed_frames / self.config.fps,
        )

    # ------------------------------------------------------------------
    # Scene capture helpers
    # ------------------------------------------------------------------
    async def _capture_scene(
        self,
        page,
        shot: VideoShot,
    ) -> CapturedScene:
        locator = page.locator(shot.selector).first
        if await locator.count() == 0:
            raise ValueError(
                f"Selector {shot.selector!r} did not match for transition "
                f"{shot.transition_id}"
            )

        await locator.scroll_into_view_if_needed(timeout=5000)
        box = await locator.bounding_box()
        if box is None:
            raise ValueError(f"Selector {shot.selector!r} has no visible bounding box")
        target = self._box_from_js(box, shot.selector)
        return CapturedScene(image=await self._capture_page(page), target=target)

    async def _capture_page(self, page):
        from PIL import Image

        return Image.open(BytesIO(await page.screenshot(full_page=False))).convert(
            "RGB"
        )

    async def _perform_typing_action(
        self,
        page,
        shot: VideoShot,
        target: Rect,
        cursor: Point,
        shot_index: int,
    ):
        frames = []
        locator = page.locator(shot.selector).first
        await locator.click(timeout=5000)
        try:
            await locator.fill("", timeout=3000)
        except Exception:
            pass

        typed = typing_frames(
            shot.value or "",
            seed=self.config.random_seed + shot_index,
            speed=self.config.action_speed,
        )
        previous_text_length = 0
        for typed_frame in typed:
            new_text = typed_frame.text[previous_text_length:]
            previous_text_length = len(typed_frame.text)
            if new_text:
                await page.keyboard.type(new_text)
            current_image = await self._capture_page(page)
            frame = self._compose_frame(
                current_image,
                target,
                cursor,
                zoom_progress=1.0,
                caret_visible=typed_frame.caret_visible,
            )
            repeats = max(1, self._scaled_frame_count(0.08))
            frames.extend([frame.copy() for _ in range(repeats)])
        return frames

    async def _perform_non_typing_action(self, page, shot: VideoShot) -> None:
        locator = page.locator(shot.selector).first
        action_type = shot.action_type.lower()
        if action_type in {"select", "option"} and shot.value is not None:
            await locator.select_option(shot.value, timeout=5000)
        else:
            await locator.click(timeout=5000)
        await self._wait_for_page_stability(page)

    async def _wait_for_page_stability(self, page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            try:
                await page.wait_for_load_state("load", timeout=2000)
            except PlaywrightTimeoutError:
                pass

    # ------------------------------------------------------------------
    # Frame-phase builders
    # ------------------------------------------------------------------
    def _scaled_frame_count(self, seconds: float) -> int:
        speed = max(0.1, self.config.action_speed)
        return max(1, int(self.config.fps * seconds / speed))

    def _rest_frames(self, image, target: Rect, cursor: Point, intro: bool):
        """Static "rest" frames: window fully zoomed-out, cursor still."""
        count = self._scaled_frame_count(self.config.phase_rest_intro)
        frames = []
        for _ in range(count):
            frames.append(self._compose_frame(image, target, cursor, zoom_progress=0.0))
        return frames

    def _zoom_frames(self, image, target: Rect, cursor: Point, zoom_in: bool):
        """Zoom in (or out) between the rest state and the focused state."""
        count = self._scaled_frame_count(
            self.config.phase_zoom_in if zoom_in else self.config.phase_zoom_out
        )
        frames = []
        for index in range(count):
            fraction = (index + 1) / count
            # Easing is applied inside ``window_transform_for_progress``
            # via smootherstep; we just feed it a linear fraction.
            progress = fraction if zoom_in else 1.0 - fraction
            frames.append(
                self._compose_frame(image, target, cursor, zoom_progress=progress)
            )
        return frames

    def _cursor_frames(self, image, target: Rect, start: Point, end: Point):
        count = self._scaled_frame_count(self.config.phase_cursor_move)
        frames = []
        for index in range(count):
            fraction = (index + 1) / count
            cursor = curved_cursor_path(start, end, fraction)
            frames.append(
                self._compose_frame(
                    image,
                    target,
                    cursor,
                    zoom_progress=1.0,
                )
            )
        return frames

    def _press_frames(self, image, target: Rect, cursor: Point):
        """Brief visual "click press" feedback: the cursor scales down
        for a couple of frames, then back up.  Subtle enough that it
        reads as tactile feedback rather than a flashy effect."""
        count = max(2, self.config.click_press_frames)
        frames = []
        for index in range(count):
            press = 1.0 - 0.18 * (1.0 - abs(index - count / 2.0) / (count / 2.0))
            frames.append(
                self._compose_frame(
                    image,
                    target,
                    cursor,
                    zoom_progress=1.0,
                    cursor_press=press,
                )
            )
        return frames

    def _hold_frames(self, image, target: Rect, cursor: Point):
        count = self._scaled_frame_count(self.config.phase_action_hold)
        frames = []
        for _ in range(count):
            frames.append(self._compose_frame(image, target, cursor, zoom_progress=1.0))
        return frames

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------
    def _box_from_js(self, box: dict, selector: str) -> Rect:
        values = [box.get("x"), box.get("y"), box.get("width"), box.get("height")]
        if any(value is None or value != value for value in values):
            raise ValueError(f"Selector {selector!r} has no complete bounding box")
        rect = Rect(
            float(box["x"]),
            float(box["y"]),
            float(box["width"]),
            float(box["height"]),
        )
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"Selector {selector!r} has an invalid bounding box")
        return rect

    def _build_window_params(self) -> WindowParams:
        cfg = self.config
        # Rest card size: same proportions as the reference video
        # (about 72% of the frame's smaller dimension, preserving the
        # page aspect ratio so the captured screenshot is never
        # squished).
        page_aspect = cfg.width / cfg.height
        rest_height = cfg.height * cfg.window_scale
        rest_width = rest_height * page_aspect
        return WindowParams(
            frame_width=cfg.width,
            frame_height=cfg.height,
            rest_width=rest_width,
            rest_height=rest_height,
            corner_radius=cfg.window_corner_radius,
            background_color=cfg.window_background_color,
            shadow_offset_y=cfg.window_shadow_offset_y,
            shadow_blur=cfg.window_shadow_blur,
            shadow_opacity=cfg.window_shadow_opacity,
            shadow_halo_blur=cfg.window_shadow_halo_blur,
            shadow_halo_opacity=cfg.window_shadow_halo_opacity,
            max_zoom=cfg.window_focus_zoom,
            focus_padding=cfg.focus_padding,
        )

    def _compose_frame(
        self,
        image,
        target: Rect,
        cursor: Point,
        zoom_progress: float,
        caret_visible: bool = False,
        cursor_press: float = 1.0,
    ):
        """Render a single output frame.

        The captured ``image`` (full-page screenshot at viewport size)
        is placed onto the output frame according to ``zoom_progress``
        (0.0 = window at rest, 1.0 = focused on target).  The ``cursor``
        is expressed in *screenshot* coordinates and is mapped onto the
        output frame using the current window transform -- this keeps
        the cursor visually "attached" to its UI element during the
        zoom.  When the window is visible (zoomed out), a rounded
        corner mask and soft drop shadow are applied so the page reads
        as a floating card; when fully zoomed in, those decorations
        fall outside the frame and are skipped.
        """
        from PIL import Image, ImageFilter, ImageDraw

        params = self._window_params
        transform = window_transform_for_progress(params, target, zoom_progress)

        # Background -- solid colour, identical to the reference video.
        frame = Image.new(
            "RGB", (params.frame_width, params.frame_height), params.background_color
        )

        # Crop the visible region of the screenshot and resize it to
        # the on-screen rectangle dictated by the transform.
        crop_box = (
            int(round(transform.crop.x)),
            int(round(transform.crop.y)),
            int(round(transform.crop.x + transform.crop.width)),
            int(round(transform.crop.y + transform.crop.height)),
        )
        # Clamp to image bounds to avoid PIL errors at the edges.
        crop_box = (
            max(0, crop_box[0]),
            max(0, crop_box[1]),
            min(image.width, crop_box[2]),
            min(image.height, crop_box[3]),
        )
        cropped = image.crop(crop_box)
        screen_w = int(round(transform.screen.width))
        screen_h = int(round(transform.screen.height))
        if cropped.size != (screen_w, screen_h):
            cropped = cropped.resize((screen_w, screen_h), Image.Resampling.LANCZOS)

        screen_x = int(round(transform.screen.x))
        screen_y = int(round(transform.screen.y))

        # Only bother with rounded corners + shadow when the card is
        # actually smaller than the frame (i.e. visible as a window).
        visibility = transform.visibility
        if visibility > 0.02 and (
            screen_w < params.frame_width - 2 or screen_h < params.frame_height - 2
        ):
            # 1. Draw the shadow on its own RGBA layer, then composite.
            shadow_layer = self._build_shadow_layer(
                screen_x,
                screen_y,
                screen_w,
                screen_h,
                params,
                visibility,
            )
            if shadow_layer is not None:
                frame_rgba = frame.convert("RGBA")
                frame_rgba = Image.alpha_composite(frame_rgba, shadow_layer)
                frame = frame_rgba.convert("RGB")

            # 2. Round the corners of the cropped card and paste it.
            mask = self._rounded_mask(
                screen_w,
                screen_h,
                params.corner_radius,
            )
            rounded = Image.new("RGBA", (screen_w, screen_h), (0, 0, 0, 0))
            rounded.paste(cropped.convert("RGBA"), (0, 0))
            rounded.putalpha(mask)
            frame.paste(rounded, (screen_x, screen_y), rounded)
        else:
            # Fully zoomed in -- just paste the (already-resized)
            # crop directly.  No shadow, no rounded corners visible.
            frame.paste(cropped, (screen_x, screen_y))

        # Cursor -- drawn on top in screen coordinates.
        cursor_screen = screen_point_for_cursor(cursor, transform, params)
        cursor_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        cursor_img = self.cursor_image
        if cursor_press != 1.0:
            scale = max(0.7, cursor_press)
            new_size = (
                max(1, int(cursor_img.width * scale)),
                max(1, int(cursor_img.height * scale)),
            )
            cursor_img = cursor_img.resize(new_size, Image.Resampling.LANCZOS)
            # Keep the hotspot proportional so the tip stays put.
            hot_x = int(self.cursor_hotspot[0] * scale)
            hot_y = int(self.cursor_hotspot[1] * scale)
        else:
            hot_x, hot_y = self.cursor_hotspot
        cursor_layer.alpha_composite(
            cursor_img,
            (
                int(cursor_screen.x - hot_x),
                int(cursor_screen.y - hot_y),
            ),
        )
        frame = Image.alpha_composite(frame.convert("RGBA"), cursor_layer).convert(
            "RGB"
        )

        # Caret -- drawn on top of the (possibly zoomed-in) target.
        if caret_visible:
            self._draw_caret(
                frame,
                image,
                target,
                transform,
                params,
            )

        return frame

    # ------------------------------------------------------------------
    # Visual helpers
    # ------------------------------------------------------------------
    def _build_shadow_layer(
        self,
        screen_x: int,
        screen_y: int,
        screen_w: int,
        screen_h: int,
        params: WindowParams,
        visibility: float,
    ):
        """Render the drop shadow (with a softer ambient halo) for the
        windowed card.  Returns an RGBA layer the size of the frame,
        or ``None`` if there is nothing visible to draw."""
        from PIL import Image, ImageFilter, ImageDraw

        if screen_w <= 0 or screen_h <= 0:
            return None

        layer = Image.new(
            "RGBA", (params.frame_width, params.frame_height), (0, 0, 0, 0)
        )

        # Primary downward shadow.
        primary = Image.new(
            "RGBA", (params.frame_width, params.frame_height), (0, 0, 0, 0)
        )
        draw = ImageDraw.Draw(primary)
        draw.rounded_rectangle(
            (
                screen_x,
                screen_y + params.shadow_offset_y,
                screen_x + screen_w,
                screen_y + screen_h + params.shadow_offset_y,
            ),
            radius=params.corner_radius,
            fill=(0, 0, 0, int(255 * params.shadow_opacity * visibility)),
        )
        primary = primary.filter(ImageFilter.GaussianBlur(radius=params.shadow_blur))

        # Wider, fainter ambient halo.
        halo = Image.new(
            "RGBA", (params.frame_width, params.frame_height), (0, 0, 0, 0)
        )
        draw = ImageDraw.Draw(halo)
        draw.rounded_rectangle(
            (
                screen_x,
                screen_y + params.shadow_offset_y,
                screen_x + screen_w,
                screen_y + screen_h + params.shadow_offset_y,
            ),
            radius=params.corner_radius,
            fill=(0, 0, 0, int(255 * params.shadow_halo_opacity * visibility)),
        )
        halo = halo.filter(ImageFilter.GaussianBlur(radius=params.shadow_halo_blur))

        layer = Image.alpha_composite(layer, halo)
        layer = Image.alpha_composite(layer, primary)
        return layer

    def _rounded_mask(self, width: int, height: int, radius: int):
        from PIL import Image, ImageDraw

        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
        return mask

    def _draw_caret(self, frame, source_image, target: Rect, transform, params):
        """Draw the text caret on top of the (zoomed) target so the
        user sees the typing cursor blinking.  The caret is positioned
        relative to the target's right edge in *screenshot* space and
        mapped to screen space using the current transform."""
        from PIL import ImageDraw

        # Caret x in screenshot coords: just inside the right edge of
        # the target's text area.  This mirrors the original behaviour.
        caret_x_source = target.x + min(
            target.width - 6,
            max(6, target.width * 0.82),
        )
        caret_top_source = target.y + 6
        caret_bot_source = target.y + target.height - 6

        top_screen = screen_point_for_cursor(
            Point(caret_x_source, caret_top_source), transform, params
        )
        bot_screen = screen_point_for_cursor(
            Point(caret_x_source, caret_bot_source), transform, params
        )

        draw = ImageDraw.Draw(frame)
        draw.line(
            (top_screen.x, top_screen.y, bot_screen.x, bot_screen.y),
            fill=(25, 25, 25),
            width=max(1, int(2 * transform.screen.width / transform.crop.width)),
        )
