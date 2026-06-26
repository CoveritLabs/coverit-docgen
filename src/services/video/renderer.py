from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urljoin
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
    click_point: Point
    scroll: Point
    cursor_kind: CursorKind
    locator: object | None = None


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
                    try:
                        scene = pending_scene or await self._capture_scene_when_ready(
                            page,
                            shot,
                        )
                    except ValueError as exc:
                        if await self._perform_missing_selector_action(
                            page,
                            shot,
                            exc,
                        ):
                            pending_scene = None
                            already_focused = False
                            continue
                        raise
                    pending_scene = None
                    if scene is None:
                        await self._perform_nonvisual_action(page, shot)
                        already_focused = False
                        continue

                    target_center = scene.click_point

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
                                scene.locator,
                                scene.target,
                                target_center,
                                scene.cursor_kind,
                                shot_index,
                            )
                        )
                        release_image = await self._capture_page(page)
                    else:
                        await self._perform_non_typing_action(
                            page,
                            shot,
                            scene.locator,
                            target_center,
                        )
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
                        next_shot = timeline.shots[shot_index + 1]
                        next_scene = await self._capture_next_scene_after_action(
                            page,
                            shot,
                            scene,
                            target_center,
                            next_shot,
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
                                next_scene.click_point,
                            )
                        )
                        pending_scene = next_scene
                        previous_cursor = next_scene.click_point
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
    async def _try_capture_scene(
        self,
        page,
        shot: VideoShot,
    ) -> CapturedScene | None:
        return await self._capture_scene_when_ready(page, shot, timeout_ms=0)

    async def _capture_scene_when_ready(
        self,
        page,
        shot: VideoShot,
        timeout_ms: int = 7000,
    ) -> CapturedScene | None:
        deadline = monotonic() + timeout_ms / 1000
        last_error: ValueError | None = None

        while True:
            try:
                return await self._capture_scene(page, shot)
            except ValueError as exc:
                message = str(exc)
                if "has no visible bounding box" in message:
                    if await self._is_nonvisual_action_target(page, shot):
                        return None
                    last_error = exc
                elif "did not match" in message:
                    last_error = exc
                else:
                    raise

            if monotonic() >= deadline:
                raise last_error or ValueError(
                    f"Selector {shot.selector!r} was not ready for transition "
                    f"{shot.transition_id}"
                )

            await self._wait_for_timeout(page, 250)

    async def _capture_next_scene_after_action(
        self,
        page,
        shot: VideoShot,
        scene: CapturedScene,
        click_point: Point,
        next_shot: VideoShot,
    ) -> CapturedScene | None:
        try:
            return await self._capture_scene_when_ready(page, next_shot)
        except ValueError:
            if shot.has_typing:
                await self._press_enter_to_materialize_result(page, next_shot)
                try:
                    return await self._capture_scene_when_ready(
                        page,
                        next_shot,
                        timeout_ms=3500,
                    )
                except ValueError:
                    return None

            if shot.has_typing or scene.locator is None:
                raise

            action_type = shot.action_type.lower()
            if action_type not in {"", "click", "press", "tap"}:
                raise

            await self._click_locator_direct(
                page,
                scene.locator,
                scene.target,
                click_point,
            )
            await self._wait_for_page_stability(page)
            try:
                return await self._capture_scene_when_ready(page, next_shot)
            except ValueError:
                return None

    async def _capture_scene(
        self,
        page,
        shot: VideoShot,
    ) -> CapturedScene:
        locator, box = await self._visible_locator_for(page, shot)
        scroll = await self._page_scroll(page)
        target = self._box_from_js(box, shot.selector)
        click_point = self._visible_click_point(target)
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
            click_point=click_point,
            scroll=scroll,
            cursor_kind=await self._cursor_kind_for(locator, shot),
            locator=locator,
        )

    async def _visible_locator_for(self, page, shot: VideoShot):
        any_match = False
        for locator in self._locator_candidates(page, shot.selector):
            count = await locator.count()
            if count == 0:
                continue
            any_match = True

            fallback = None
            for index in range(count):
                nth = getattr(locator, "nth", None)
                if nth is None:
                    if index > 0:
                        break
                    candidate = locator.first
                else:
                    candidate = nth(index)
                await self._scroll_locator_to_center(page, candidate)
                box = await candidate.bounding_box()
                if box is not None:
                    if fallback is None:
                        fallback = (candidate, box)
                    try:
                        target = self._box_from_js(box, shot.selector)
                    except ValueError:
                        continue
                    if await self._candidate_receives_pointer(
                        candidate,
                        self._visible_click_point(target),
                    ):
                        return candidate, box

            if fallback is not None:
                return fallback

        if not any_match:
            raise ValueError(
                f"Selector {shot.selector!r} did not match for transition "
                f"{shot.transition_id}"
            )

        raise ValueError(f"Selector {shot.selector!r} has no visible bounding box")

    def _locator_candidates(self, page, selector: str):
        seen: set[str] = set()

        def add_css(css: str):
            if css and css not in seen:
                seen.add(css)
                yield page.locator(css)

        yield from add_css(selector)

        normalized = self._normalize_selector(selector)
        if normalized != selector:
            yield from add_css(normalized)

        href = self._href_from_selector(selector)
        if not href:
            return

        href_variants = self._href_variants(href)
        for href_value in href_variants:
            escaped = self._css_string(href_value)
            yield from add_css(f'a[href="{escaped}"]')
            yield from add_css(f'a[href$="{escaped}"]')
            yield from add_css(f'a[href*="{escaped}"]')
            yield from add_css(f'a[href$="{escaped}" i]')
            yield from add_css(f'a[href*="{escaped}" i]')

        for text in self._link_text_candidates(href):
            locator = page.locator("a")
            filter_method = getattr(locator, "filter", None)
            if filter_method is not None:
                try:
                    yield filter_method(has_text=text)
                except TypeError:
                    pass

    def _normalize_selector(self, selector: str) -> str:
        return (
            selector.replace("\\/", "/")
            .replace('\\"', '"')
        )

    def _href_from_selector(self, selector: str) -> str | None:
        match = re.search(r"""href\s*=\s*(['"])(.*?)\1""", selector)
        if not match:
            return None
        return self._normalize_selector(match.group(2))

    def _href_variants(self, href: str) -> list[str]:
        variants = []
        for value in {
            href,
            href.rstrip("/"),
            href.lower(),
            href.lower().rstrip("/"),
        }:
            if value and value not in variants:
                variants.append(value)
        return variants

    def _link_text_candidates(self, href: str) -> list[str]:
        path = href.split("?", 1)[0].strip("/")
        parts = [part for part in path.split("/") if part]
        candidates: list[str] = []
        if parts:
            candidates.append(parts[-1])
        if len(parts) >= 2:
            candidates.append("/".join(parts[-2:]))
        return candidates

    def _css_string(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    async def _candidate_receives_pointer(self, locator, point: Point) -> bool:
        evaluate = getattr(locator, "evaluate", None)
        if evaluate is None:
            return True

        try:
            receives_pointer = await evaluate(
                """(element, point) => {
                    const hit = document.elementFromPoint(point.x, point.y);
                    return hit === element || element.contains(hit);
                }""",
                {"x": point.x, "y": point.y},
            )
        except Exception:
            return True

        return bool(receives_pointer)

    async def _scroll_locator_to_center(self, page, locator) -> None:
        evaluate = getattr(locator, "evaluate", None)
        if evaluate is not None:
            try:
                result = await evaluate(
                    """element => {
                        element.scrollIntoView({
                            block: "center",
                            inline: "center"
                        });
                    }"""
                )
                await self._wait_for_timeout(page, 100)
                if result is None:
                    return
            except Exception:
                pass

        try:
            await locator.scroll_into_view_if_needed(timeout=5000)
        except PlaywrightTimeoutError:
            pass
        await self._wait_for_timeout(page, 50)

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

    async def _wait_for_timeout(self, page, milliseconds: int) -> None:
        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is None:
            return
        try:
            await wait_for_timeout(milliseconds)
        except Exception:
            pass

    async def _cursor_kind_for(self, locator, shot: VideoShot) -> CursorKind:
        if shot.has_typing:
            return "text"

        return self._cursor_kind_from_metadata(await self._element_metadata(locator))

    async def _element_metadata(self, locator) -> dict:
        evaluate = getattr(locator, "evaluate", None)
        if evaluate is None:
            return {}
        try:
            value = await evaluate(
                """element => {
                    const style = window.getComputedStyle(element);
                    return {
                        tagName: element.tagName,
                        type: element.getAttribute("type") || "",
                        name: element.getAttribute("name") || "",
                        id: element.getAttribute("id") || "",
                        role: element.getAttribute("role") || "",
                        href: element.getAttribute("href") || "",
                        cursor: style.cursor || "",
                        contentEditable: element.isContentEditable
                    };
                }"""
            )
        except Exception:
            return {}

        return value if isinstance(value, dict) else {}

    async def _is_nonvisual_action_target(self, page, shot: VideoShot) -> bool:
        locator = page.locator(shot.selector)
        try:
            count = await locator.count()
        except Exception:
            return False

        for index in range(min(count, 5)):
            metadata = await self._element_metadata(locator.nth(index))
            if self._metadata_is_nonvisual_target(metadata):
                return True
        return False

    def _metadata_is_nonvisual_target(self, metadata: dict) -> bool:
        tag = str(metadata.get("tagName") or metadata.get("tag") or "").lower()
        input_type = str(metadata.get("type") or "").lower()
        name = str(metadata.get("name") or "").lower()
        element_id = str(metadata.get("id") or "").lower()

        if tag == "input" and input_type == "hidden":
            return True

        technical_names = {
            "authenticity_token",
            "csrf",
            "csrf_token",
            "webauthn-support",
        }
        return tag == "input" and (
            name in technical_names
            or element_id in technical_names
            or name.startswith("_")
        )

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

    def _visible_click_point(self, target: Rect) -> Point:
        viewport_right = float(self.config.width)
        viewport_bottom = float(self.config.height)
        visible_left = max(0.0, target.x)
        visible_top = max(0.0, target.y)
        visible_right = min(viewport_right, target.x + target.width)
        visible_bottom = min(viewport_bottom, target.y + target.height)

        if visible_right > visible_left and visible_bottom > visible_top:
            return Point(
                (visible_left + visible_right) / 2.0,
                (visible_top + visible_bottom) / 2.0,
            )

        return Point(
            min(max(target.center.x, 0.0), max(0.0, viewport_right - 1.0)),
            min(max(target.center.y, 0.0), max(0.0, viewport_bottom - 1.0)),
        )

    def _cursor_kind_for_position(
        self,
        cursor_kind: CursorKind,
        cursor: Point,
        target: Rect,
    ) -> CursorKind:
        if cursor_kind != "hand":
            return cursor_kind

        inside_x = target.x <= cursor.x <= target.x + target.width
        inside_y = target.y <= cursor.y <= target.y + target.height
        return "hand" if inside_x and inside_y else "default"

    async def _perform_typing_action(
        self,
        page,
        shot: VideoShot,
        locator,
        target: Rect,
        cursor: Point,
        cursor_kind: CursorKind,
        shot_index: int,
    ):
        frames = []
        if locator is None:
            locator, _ = await self._visible_locator_for(page, shot)
        await self._click_at(page, locator, cursor)
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
                cursor_kind=self._cursor_kind_for_position(
                    cursor_kind,
                    cursor,
                    target,
                ),
            )
            repeats = max(1, self._scaled_frame_count(0.08))
            frames.extend([frame.copy() for _ in range(repeats)])
        await self._wait_for_page_stability(page)
        return frames

    async def _perform_non_typing_action(
        self,
        page,
        shot: VideoShot,
        locator,
        click_point: Point,
    ) -> None:
        if locator is None:
            locator, _ = await self._visible_locator_for(page, shot)
        action_type = shot.action_type.lower()
        metadata = await self._element_metadata(locator)
        is_native_select = str(metadata.get("tagName") or "").lower() == "select"
        metadata_unavailable = not metadata

        await self._click_at(page, locator, click_point)

        if (
            action_type in {"select", "option"}
            and shot.value is not None
            and (is_native_select or metadata_unavailable)
        ):
            try:
                await locator.select_option(shot.value, timeout=5000)
            except Exception:
                if is_native_select:
                    raise
        await self._wait_for_page_stability(page)

    async def _perform_nonvisual_action(self, page, shot: VideoShot) -> None:
        locator = page.locator(shot.selector)
        if await locator.count() == 0:
            raise ValueError(
                f"Selector {shot.selector!r} did not match for transition "
                f"{shot.transition_id}"
            )

        action_type = shot.action_type.lower()
        target = locator.first
        if shot.value is not None and (
            shot.has_typing or action_type in {"select", "option"}
        ):
            await self._set_nonvisual_value(target, shot.value)
        elif action_type in {"click", "press", "tap"}:
            await self._click_nonvisual(target)

        await self._wait_for_page_stability(page)

    async def _perform_missing_selector_action(
        self,
        page,
        shot: VideoShot,
        exc: ValueError,
    ) -> bool:
        if "did not match" not in str(exc):
            return False

        action_type = shot.action_type.lower()
        if action_type not in {"", "click", "press", "tap"}:
            return False

        href = self._href_from_selector(shot.selector)
        if not href:
            return False

        await self._navigate_to_href(page, href)
        return True

    async def _press_enter_to_materialize_result(
        self,
        page,
        next_shot: VideoShot,
    ) -> None:
        if not self._href_from_selector(next_shot.selector):
            return

        keyboard = getattr(page, "keyboard", None)
        press = getattr(keyboard, "press", None)
        if press is None:
            return

        try:
            await press("Enter")
        except Exception:
            return

        await self._wait_for_page_stability(page)

    async def _navigate_to_href(self, page, href: str) -> None:
        current_url = await self._current_page_url(page)
        target_url = urljoin(current_url, href)
        await page.goto(target_url, wait_until="load", timeout=30000)
        await self._wait_for_page_stability(page)

    async def _current_page_url(self, page) -> str:
        url = getattr(page, "url", "")
        if isinstance(url, str) and url:
            return url

        evaluate = getattr(page, "evaluate", None)
        if evaluate is None:
            return ""

        try:
            value = await evaluate("() => window.location.href")
        except Exception:
            return ""

        return value if isinstance(value, str) else ""

    async def _set_nonvisual_value(self, locator, value: str) -> None:
        evaluate = getattr(locator, "evaluate", None)
        if evaluate is None:
            return

        try:
            await evaluate(
                """(element, value) => {
                    if ("value" in element) {
                        element.value = value;
                    }
                    element.setAttribute("value", value);
                    element.dispatchEvent(new Event("input", { bubbles: true }));
                    element.dispatchEvent(new Event("change", { bubbles: true }));
                }""",
                value,
            )
        except Exception:
            pass

    async def _click_nonvisual(self, locator) -> None:
        await self._dispatch_dom_click(locator)

    async def _click_at(self, page, locator, point: Point) -> None:
        mouse = getattr(page, "mouse", None)
        mouse_click = getattr(mouse, "click", None)
        if mouse_click is not None:
            mouse_move = getattr(mouse, "move", None)
            if mouse_move is not None:
                await mouse_move(point.x, point.y)
            await mouse_click(point.x, point.y)
            return

        await locator.click(timeout=5000)

    async def _click_locator_direct(
        self,
        page,
        locator,
        target: Rect,
        point: Point,
    ) -> None:
        click = getattr(locator, "click", None)
        position = {
            "x": min(max(point.x - target.x, 0.0), max(1.0, target.width)),
            "y": min(max(point.y - target.y, 0.0), max(1.0, target.height)),
        }
        if click is not None:
            if await self._try_locator_click(click, position, force=False):
                return
            if await self._try_locator_click(click, position, force=True):
                return

        if await self._dispatch_dom_click(locator):
            return

        await self._activate_locator_with_keyboard(page, locator)

    async def _try_locator_click(
        self,
        click,
        position: dict[str, float],
        force: bool,
    ) -> bool:
        kwargs = {
            "position": position,
            "timeout": 1800,
        }
        if force:
            kwargs["force"] = True

        try:
            await click(**kwargs)
            return True
        except TypeError:
            try:
                await click(timeout=1800, force=force)
                return True
            except TypeError:
                try:
                    await click(timeout=1800)
                    return True
                except Exception:
                    return False
            except Exception:
                return False
        except Exception:
            return False

    async def _dispatch_dom_click(self, locator) -> bool:
        evaluate = getattr(locator, "evaluate", None)
        if evaluate is None:
            return False

        try:
            return bool(
                await evaluate(
                    """element => {
                        const options = {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        };
                        element.dispatchEvent(new PointerEvent("pointerdown", options));
                        element.dispatchEvent(new MouseEvent("mousedown", options));
                        element.dispatchEvent(new PointerEvent("pointerup", options));
                        element.dispatchEvent(new MouseEvent("mouseup", options));
                        element.dispatchEvent(new MouseEvent("click", options));
                        if (typeof element.click === "function") {
                            element.click();
                        }
                        return true;
                    }"""
                )
            )
        except Exception:
            return False

    async def _activate_locator_with_keyboard(
        self,
        page,
        locator,
    ) -> None:
        focus = getattr(locator, "focus", None)
        if focus is not None:
            try:
                await focus(timeout=1000)
            except TypeError:
                try:
                    await focus()
                except Exception:
                    pass
            except Exception:
                pass

        keyboard = getattr(page, "keyboard", None)
        press = getattr(keyboard, "press", None)
        if press is None:
            return

        try:
            await press("Enter")
        except Exception:
            pass

    async def _wait_for_page_stability(self, page) -> None:
        await self._wait_for_timeout(page, 150)
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
                cursor_kind=self._cursor_kind_for_position(
                    cursor_kind,
                    cursor,
                    target,
                ),
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
                    cursor_kind=self._cursor_kind_for_position(
                        cursor_kind,
                        cursor,
                        target,
                    ),
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
            cursor_kind = self._cursor_kind_for_position(
                cursor_kind,
                cursor,
                target,
            )
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
            cursor_kind = self._cursor_kind_for_position(
                cursor_kind,
                cursor,
                target,
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
                    cursor_kind=self._cursor_kind_for_position(
                        cursor_kind,
                        cursor,
                        target,
                    ),
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
                cursor_kind=self._cursor_kind_for_position(
                    cursor_kind,
                    cursor,
                    target,
                ),
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

        cursor_kind = self._cursor_kind_for_position(cursor_kind, cursor, target)
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
