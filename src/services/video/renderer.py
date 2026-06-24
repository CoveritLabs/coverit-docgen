from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Iterable

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.core.playwright import playwright_manager
from src.services.video.config import VideoRenderConfig
from src.services.video.cursor import CursorKind, load_cursor_image
from src.services.video.effects import (
    Point,
    Rect,
    WindowParams,
    curved_cursor_path,
    ease_in_out_cubic,
    focused_window_transform,
    lerp_rect,
    screen_point_for_cursor,
    window_transform_for_progress,
)
from src.services.video.timeline import VideoFlowTimeline, VideoShot
from src.services.video.typing import typing_frames


@dataclass(frozen=True)
class CapturedScene:
    image: object
    target: Rect
    document_target: Rect
    scroll: Point
    cursor_kind: CursorKind


@dataclass(frozen=True)
class RenderOutput:
    frame_paths: list[Path]
    duration_seconds: float


class FrameSink:
    """Streams rendered frames to disk while preserving the output contract."""

    def __init__(self, frame_dir: Path, fps: int):
        self.frame_dir = frame_dir
        self.fps = fps
        self.frame_paths: list[Path] = []
        self.elapsed_frames = 0

    def write(self, frames: Iterable[object]) -> None:
        for frame in frames:
            self.write_frame(frame)

    def write_frame(self, frame) -> None:
        self.elapsed_frames += 1
        path = self.frame_dir / f"frame_{self.elapsed_frames:05d}.png"
        frame.save(path)
        self.frame_paths.append(path)

    @property
    def duration_seconds(self) -> float:
        return self.elapsed_frames / self.fps


class BrowserFrameRenderer:
    """Renders browser interactions as a sequence of PNG frames."""

    _TEXT_INPUT_TYPES = {
        "",
        "email",
        "number",
        "password",
        "search",
        "tel",
        "text",
        "url",
    }
    _HAND_INPUT_TYPES = {"button", "checkbox", "radio", "reset", "submit"}
    _HAND_ROLES = {
        "button",
        "checkbox",
        "link",
        "menuitem",
        "option",
        "radio",
        "switch",
        "tab",
    }

    def __init__(self, config: VideoRenderConfig):
        self.config = config
        self.cursor_assets = {
            "default": load_cursor_image("default"),
            "hand": load_cursor_image("hand"),
            "text": load_cursor_image("text"),
        }
        self.cursor_image, self.cursor_hotspot = self.cursor_assets["default"]
        self._window_params = self._build_window_params()

    async def render(
        self,
        timelines: list[VideoFlowTimeline],
        frame_dir: Path,
    ) -> RenderOutput:
        if playwright_manager._browser is None:
            raise RuntimeError("Playwright browser not started. Call start() first.")

        frame_dir.mkdir(parents=True, exist_ok=True)
        sink = FrameSink(frame_dir, self.config.fps)

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

                previous_cursor = Point(
                    self.config.width * 0.12,
                    self.config.height * 0.85,
                )
                previous_cursor_kind: CursorKind = "default"
                pending_scene: CapturedScene | None = None
                already_focused = False

                for shot_index, shot in enumerate(timeline.shots):
                    scene = pending_scene or await self._capture_scene(page, shot)
                    pending_scene = None
                    target_center = scene.target.center

                    if already_focused:
                        already_focused = False
                    else:
                        sink.write(
                            self._rest_frames(
                                scene.image,
                                scene.target,
                                previous_cursor,
                                previous_cursor_kind,
                            )
                        )
                        sink.write(
                            self._zoom_frames(
                                scene.image,
                                scene.target,
                                previous_cursor,
                                previous_cursor_kind,
                                zoom_in=True,
                            )
                        )
                        sink.write(
                            self._cursor_frames(
                                scene.image,
                                scene.target,
                                previous_cursor,
                                target_center,
                                previous_cursor_kind,
                                scene.cursor_kind,
                            )
                        )

                    if shot.has_typing:
                        sink.write(
                            await self._perform_typing_action(
                                page,
                                shot,
                                scene.target,
                                target_center,
                                scene.cursor_kind,
                                shot_index,
                            )
                        )
                        release_image = await self._capture_page(page)
                    else:
                        await self._perform_non_typing_action(page, shot)
                        release_image = await self._capture_page(page)
                        sink.write(
                            self._press_frames(
                                release_image,
                                scene.target,
                                target_center,
                                scene.cursor_kind,
                            )
                        )

                    release_scene = replace(scene, image=release_image)
                    sink.write(
                        self._hold_frames(
                            release_image,
                            scene.target,
                            target_center,
                            scene.cursor_kind,
                        )
                    )

                    next_scene = None
                    if shot_index + 1 < len(timeline.shots):
                        next_scene = await self._capture_scene(
                            page,
                            timeline.shots[shot_index + 1],
                        )

                    if next_scene and self._should_stick_to_next(
                        release_scene,
                        next_scene,
                    ):
                        sink.write(
                            self._focus_pan_frames(
                                release_scene,
                                next_scene,
                                target_center,
                                next_scene.target.center,
                            )
                        )
                        pending_scene = next_scene
                        previous_cursor = next_scene.target.center
                        previous_cursor_kind = next_scene.cursor_kind
                        already_focused = True
                    else:
                        sink.write(
                            self._zoom_frames(
                                release_image,
                                scene.target,
                                target_center,
                                scene.cursor_kind,
                                zoom_in=False,
                            )
                        )
                        sink.write(
                            self._rest_frames(
                                release_image,
                                scene.target,
                                target_center,
                                scene.cursor_kind,
                            )
                        )
                        if next_scene:
                            pending_scene = next_scene
                            previous_cursor = self._document_point_in_scene(
                                release_scene.document_target.center,
                                next_scene,
                            )
                        else:
                            previous_cursor = target_center
                        previous_cursor_kind = scene.cursor_kind
            finally:
                await page.close()

        return RenderOutput(
            frame_paths=sink.frame_paths,
            duration_seconds=sink.duration_seconds,
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
        scroll = await self._page_scroll(page)
        box = await locator.bounding_box()
        if box is None:
            raise ValueError(f"Selector {shot.selector!r} has no visible bounding box")

        target = self._box_from_js(box, shot.selector)
        document_target = Rect(
            target.x + scroll.x,
            target.y + scroll.y,
            target.width,
            target.height,
        )
        return CapturedScene(
            image=await self._capture_page(page),
            target=target,
            document_target=document_target,
            scroll=scroll,
            cursor_kind=await self._cursor_kind_for(locator, shot),
        )

    async def _capture_page(self, page):
        from PIL import Image

        return Image.open(BytesIO(await page.screenshot(full_page=False))).convert(
            "RGB"
        )

    async def _page_scroll(self, page) -> Point:
        evaluate = getattr(page, "evaluate", None)
        if evaluate is None:
            return Point(0.0, 0.0)

        try:
            value = await evaluate(
                """() => ({
                    x: window.scrollX || window.pageXOffset || 0,
                    y: window.scrollY || window.pageYOffset || 0
                })"""
            )
        except Exception:
            return Point(0.0, 0.0)

        if not isinstance(value, dict):
            return Point(0.0, 0.0)
        return Point(float(value.get("x") or 0.0), float(value.get("y") or 0.0))

    async def _cursor_kind_for(self, locator, shot: VideoShot) -> CursorKind:
        if shot.has_typing:
            return "text"

        evaluate = getattr(locator, "evaluate", None)
        if evaluate is None:
            return "default"

        try:
            metadata = await evaluate(
                """element => {
                    const style = window.getComputedStyle(element);
                    return {
                        tagName: element.tagName,
                        type: element.getAttribute("type") || "",
                        role: element.getAttribute("role") || "",
                        href: element.getAttribute("href") || "",
                        cursor: style.cursor || "",
                        contentEditable: element.isContentEditable
                    };
                }"""
            )
        except Exception:
            return "default"

        return self._cursor_kind_from_metadata(metadata)

    def _cursor_kind_from_metadata(self, metadata) -> CursorKind:
        if not isinstance(metadata, dict):
            return "default"

        tag = str(metadata.get("tagName") or metadata.get("tag") or "").lower()
        input_type = str(metadata.get("type") or "").lower()
        role = str(metadata.get("role") or "").lower()
        css_cursor = str(metadata.get("cursor") or "").lower()
        href = str(metadata.get("href") or "")
        content_editable = metadata.get("contentEditable") in {
            True,
            "true",
            "plaintext-only",
        }

        if (
            css_cursor == "text"
            or content_editable
            or role == "textbox"
            or tag == "textarea"
            or (tag == "input" and input_type in self._TEXT_INPUT_TYPES)
        ):
            return "text"

        if (
            css_cursor == "pointer"
            or role in self._HAND_ROLES
            or tag in {"button", "select", "summary"}
            or (tag == "a" and href)
            or (tag == "input" and input_type in self._HAND_INPUT_TYPES)
        ):
            return "hand"

        return "default"

    async def _perform_typing_action(
        self,
        page,
        shot: VideoShot,
        target: Rect,
        cursor: Point,
        cursor_kind: CursorKind,
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
                cursor_kind=cursor_kind,
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

    def _rest_frames(
        self,
        image,
        target: Rect,
        cursor: Point,
        cursor_kind: CursorKind,
    ):
        count = self._scaled_frame_count(self.config.phase_rest_intro)
        return [
            self._compose_frame(
                image,
                target,
                cursor,
                zoom_progress=0.0,
                cursor_kind=cursor_kind,
            )
            for _ in range(count)
        ]

    def _zoom_frames(
        self,
        image,
        target: Rect,
        cursor: Point,
        cursor_kind: CursorKind,
        zoom_in: bool,
    ):
        count = self._scaled_frame_count(
            self.config.phase_zoom_in if zoom_in else self.config.phase_zoom_out
        )
        frames = []
        for index in range(count):
            fraction = (index + 1) / count
            progress = fraction if zoom_in else 1.0 - fraction
            frames.append(
                self._compose_frame(
                    image,
                    target,
                    cursor,
                    zoom_progress=progress,
                    cursor_kind=cursor_kind,
                )
            )
        return frames

    def _cursor_frames(
        self,
        image,
        target: Rect,
        start: Point,
        end: Point,
        start_cursor_kind: CursorKind,
        end_cursor_kind: CursorKind,
    ):
        count = self._scaled_frame_count(self.config.phase_cursor_move)
        frames = []
        for index in range(count):
            fraction = (index + 1) / count
            cursor = curved_cursor_path(start, end, fraction)
            cursor_kind = end_cursor_kind if fraction > 0.82 else start_cursor_kind
            frames.append(
                self._compose_frame(
                    image,
                    target,
                    cursor,
                    zoom_progress=1.0,
                    cursor_kind=cursor_kind,
                )
            )
        return frames

    def _focus_pan_frames(
        self,
        start_scene: CapturedScene,
        end_scene: CapturedScene,
        start_cursor: Point,
        end_cursor: Point,
    ):
        from PIL import Image

        count = self._scaled_frame_count(self.config.phase_focus_pan)
        frames = []
        for index in range(count):
            fraction = (index + 1) / count
            eased = ease_in_out_cubic(fraction)
            blended = Image.blend(
                start_scene.image.convert("RGB"),
                end_scene.image.convert("RGB"),
                eased,
            )
            target = lerp_rect(start_scene.target, end_scene.target, eased)
            cursor = curved_cursor_path(start_cursor, end_cursor, fraction)
            cursor_kind = (
                end_scene.cursor_kind
                if fraction > 0.82
                else start_scene.cursor_kind
            )
            frames.append(
                self._compose_frame(
                    blended,
                    target,
                    cursor,
                    zoom_progress=1.0,
                    cursor_kind=cursor_kind,
                )
            )
        return frames

    def _press_frames(
        self,
        image,
        target: Rect,
        cursor: Point,
        cursor_kind: CursorKind,
    ):
        count = max(3, self.config.click_press_frames)
        minimum = max(0.1, min(1.0, self.config.click_press_scale_min))
        frames = []
        for index in range(count):
            fraction = index / (count - 1)
            depth = 1.0 - abs(fraction * 2.0 - 1.0)
            press = 1.0 - (1.0 - minimum) * depth
            frames.append(
                self._compose_frame(
                    image,
                    target,
                    cursor,
                    zoom_progress=1.0,
                    cursor_press=press,
                    cursor_kind=cursor_kind,
                )
            )
        return frames

    def _hold_frames(
        self,
        image,
        target: Rect,
        cursor: Point,
        cursor_kind: CursorKind,
    ):
        count = self._scaled_frame_count(self.config.phase_action_hold)
        return [
            self._compose_frame(
                image,
                target,
                cursor,
                zoom_progress=1.0,
                cursor_kind=cursor_kind,
            )
            for _ in range(count)
        ]

    # ------------------------------------------------------------------
    # Sticky camera helpers
    # ------------------------------------------------------------------
    def _should_stick_to_next(
        self,
        current_scene: CapturedScene,
        next_scene: CapturedScene,
    ) -> bool:
        if not self.config.camera_sticky_enabled:
            return False

        current = current_scene.document_target.center
        next_target = next_scene.document_target.center
        dx = next_target.x - current.x
        dy = next_target.y - current.y
        distance = (dx * dx + dy * dy) ** 0.5
        if distance > self.config.camera_sticky_max_distance_px:
            return False

        focused_crop, _ = focused_window_transform(
            self._window_params,
            current_scene.target,
        )
        max_dx = focused_crop.width * self.config.camera_sticky_max_axis_ratio
        max_dy = focused_crop.height * self.config.camera_sticky_max_axis_ratio
        return abs(dx) <= max_dx and abs(dy) <= max_dy

    def _document_point_in_scene(
        self,
        document_point: Point,
        scene: CapturedScene,
    ) -> Point:
        return Point(
            document_point.x - scene.scroll.x,
            document_point.y - scene.scroll.y,
        )

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
        cursor_kind: CursorKind = "default",
    ):
        from PIL import Image

        params = self._window_params
        transform = window_transform_for_progress(params, target, zoom_progress)

        frame = Image.new(
            "RGB", (params.frame_width, params.frame_height), params.background_color
        )

        crop_box = (
            int(round(transform.crop.x)),
            int(round(transform.crop.y)),
            int(round(transform.crop.x + transform.crop.width)),
            int(round(transform.crop.y + transform.crop.height)),
        )
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

        visibility = transform.visibility
        if visibility > 0.02 and (
            screen_w < params.frame_width - 2 or screen_h < params.frame_height - 2
        ):
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
            frame.paste(cropped, (screen_x, screen_y))

        cursor_screen = screen_point_for_cursor(cursor, transform, params)
        cursor_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        cursor_img, hotspot = self._cursor_asset(cursor_kind)
        if cursor_press != 1.0:
            scale = max(0.1, min(1.0, cursor_press))
            new_size = (
                max(1, int(cursor_img.width * scale)),
                max(1, int(cursor_img.height * scale)),
            )
            cursor_img = cursor_img.resize(new_size, Image.Resampling.LANCZOS)
            hot_x = int(hotspot[0] * scale)
            hot_y = int(hotspot[1] * scale)
        else:
            hot_x, hot_y = hotspot
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

        # if caret_visible:
        #     self._draw_caret(
        #         frame,
        #         image,
        #         target,
        #         transform,
        #         params,
        #     )

        return frame

    def _cursor_asset(self, cursor_kind: CursorKind):
        return self.cursor_assets.get(cursor_kind) or self.cursor_assets["default"]

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
        from PIL import Image, ImageDraw, ImageFilter

        if screen_w <= 0 or screen_h <= 0:
            return None

        layer = Image.new(
            "RGBA", (params.frame_width, params.frame_height), (0, 0, 0, 0)
        )

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
        from PIL import ImageDraw

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
