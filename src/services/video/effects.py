from dataclasses import dataclass
from math import sin, pi


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)


@dataclass(frozen=True)
class CameraFrame:
    crop_x: float
    crop_y: float
    crop_width: float
    crop_height: float
    scale: float


@dataclass(frozen=True)
class WindowParams:
    """Parameters describing how the captured page is presented as a
    floating "window" on top of a solid background.  This mirrors the
    reference video where the browser content appears as a small card
    with rounded corners and a soft drop shadow that grows to fill the
    frame when zooming in on a target."""

    frame_width: int
    frame_height: int
    rest_width: float
    rest_height: float
    corner_radius: int = 14
    background_color: tuple = (245, 245, 245)
    shadow_offset_y: int = 8
    shadow_blur: float = 30.0
    shadow_opacity: float = 0.22
    shadow_halo_blur: float = 60.0
    shadow_halo_opacity: float = 0.08
    max_zoom: float = 1.4
    focus_padding: float = 18.0


@dataclass(frozen=True)
class WindowTransform:
    """Result of interpolating between the "rest" window state and the
    "focused" state.  ``crop`` describes which region of the source
    screenshot is visible, ``screen`` describes where that region is
    placed on the output frame, and ``visibility`` (0..1) reports how
    much of the surrounding background is exposed (1.0 = full windowed
    card with shadow, 0.0 = card fills the entire frame)."""

    crop: Rect
    screen: Rect
    visibility: float


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def ease_out_cubic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1 - pow(1 - t, 3)


def ease_in_cubic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * t


def ease_in_out_cubic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def ease_out_quint(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1 - pow(1 - t, 5)


def ease_in_out_quint(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    if t < 0.5:
        return 16 * t * t * t * t * t
    return 1 - pow(-2 * t + 2, 5) / 2


def smoothstep(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def smootherstep(t: float) -> float:
    """Ken Perlin's improved smoothstep -- extra-smooth S-curve."""
    t = clamp(t, 0.0, 1.0)
    return t * t * t * (t * (t * 6 - 15) + 10)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_point(start: Point, end: Point, t: float) -> Point:
    return Point(lerp(start.x, end.x, t), lerp(start.y, end.y, t))


def lerp_rect(start: Rect, end: Rect, t: float) -> Rect:
    return Rect(
        lerp(start.x, end.x, t),
        lerp(start.y, end.y, t),
        lerp(start.width, end.width, t),
        lerp(start.height, end.height, t),
    )


def cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    """Evaluate a cubic Bezier curve at parameter ``t`` in [0, 1]."""
    u = 1.0 - t
    x = u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x
    y = u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y
    return Point(x, y)


def curved_cursor_path(start: Point, end: Point, t: float) -> Point:
    """Smoothly move the cursor from ``start`` to ``end`` along a gentle
    arc.  Uses a cubic Bezier with auto-computed control points so the
    motion feels natural rather than linear, and an ease-out quintic so
    the cursor settles softly onto its target (matching the reference
    video where the cursor glides and decelerates)."""
    if t <= 0:
        return start
    if t >= 1:
        return end

    eased = ease_out_quint(t)

    dx = end.x - start.x
    dy = end.y - start.y
    distance = (dx * dx + dy * dy) ** 0.5

    if distance < 1e-3:
        return start

    # Perpendicular unit vector (90° clockwise rotation of the
    # direction vector).  For rightward motion this points "up" in
    # screen coords (negative y), so the cursor lifts gently as it
    # travels -- the same natural arc the original implementation
    # produced via ``base.y - offset``.
    perp_x = dy / distance
    perp_y = -dx / distance

    # Arc height scales with distance but is capped so very long moves
    # do not look exaggerated.
    offset = min(80.0, distance * 0.18)

    cp1 = Point(
        start.x + dx * 0.30 + perp_x * offset,
        start.y + dy * 0.30 + perp_y * offset,
    )
    cp2 = Point(
        start.x + dx * 0.70 + perp_x * offset,
        start.y + dy * 0.70 + perp_y * offset,
    )

    return cubic_bezier(start, cp1, cp2, end, eased)


def camera_for_target(
    viewport_width: int,
    viewport_height: int,
    target: Rect,
    zoom: float,
) -> CameraFrame:
    zoom = clamp(zoom, 1.0, 1.45)
    crop_width = viewport_width / zoom
    crop_height = viewport_height / zoom
    center = target.center
    crop_x = clamp(center.x - crop_width / 2, 0, max(0, viewport_width - crop_width))
    crop_y = clamp(center.y - crop_height / 2, 0, max(0, viewport_height - crop_height))
    return CameraFrame(crop_x, crop_y, crop_width, crop_height, zoom)


def transform_point(point: Point, camera: CameraFrame) -> Point:
    return Point(
        (point.x - camera.crop_x) * camera.scale,
        (point.y - camera.crop_y) * camera.scale,
    )


def transform_rect(rect: Rect, camera: CameraFrame) -> Rect:
    top_left = transform_point(Point(rect.x, rect.y), camera)
    return Rect(
        top_left.x,
        top_left.y,
        rect.width * camera.scale,
        rect.height * camera.scale,
    )


def expand_rect(rect: Rect, padding: float, max_width: int, max_height: int) -> Rect:
    x = clamp(rect.x - padding, 0, max_width)
    y = clamp(rect.y - padding, 0, max_height)
    right = clamp(rect.x + rect.width + padding, 0, max_width)
    bottom = clamp(rect.y + rect.height + padding, 0, max_height)
    return Rect(x, y, max(1, right - x), max(1, bottom - y))


def rest_window_rect(params: WindowParams) -> Rect:
    """Rectangle (in screen coordinates) where the captured page sits
    when the camera is fully zoomed out."""
    x = (params.frame_width - params.rest_width) / 2.0
    y = (params.frame_height - params.rest_height) / 2.0
    return Rect(x, y, params.rest_width, params.rest_height)


def focused_window_transform(
    params: WindowParams,
    target: Rect,
) -> tuple[Rect, Rect]:
    """Crop region of the source screenshot and the on-screen rectangle
    that together describe the fully-zoomed-in state.  The crop is
    centred on ``target`` and just large enough that the target fills
    most of the frame; the screen rectangle is the full frame so the
    crop is rendered at 1:1 pixel scale."""
    zoom = clamp(params.max_zoom, 1.0, 2.0)
    crop_width = params.frame_width / zoom
    crop_height = params.frame_height / zoom

    # Pad the target so the zoomed view does not hug the element edges.
    padded = expand_rect(
        target,
        params.focus_padding,
        params.frame_width,
        params.frame_height,
    )
    center = padded.center
    crop_x = clamp(
        center.x - crop_width / 2,
        0,
        max(0.0, params.frame_width - crop_width),
    )
    crop_y = clamp(
        center.y - crop_height / 2,
        0,
        max(0.0, params.frame_height - crop_height),
    )
    crop = Rect(crop_x, crop_y, crop_width, crop_height)
    screen = Rect(0.0, 0.0, float(params.frame_width), float(params.frame_height))
    return crop, screen


def window_transform_for_progress(
    params: WindowParams,
    target: Rect,
    progress: float,
) -> WindowTransform:
    """Interpolate between the "rest" (windowed card) and "focused"
    (full-frame zoom on target) states.  ``progress`` 0 means at rest,
    1 means fully focused.  Uses smootherstep for the easing so the
    transition is buttery on both the way in and the way out."""
    progress = clamp(progress, 0.0, 1.0)
    eased = smootherstep(progress)

    rest_screen = rest_window_rect(params)
    rest_crop = Rect(0.0, 0.0, float(params.frame_width), float(params.frame_height))

    focused_crop, focused_screen = focused_window_transform(params, target)

    crop = lerp_rect(rest_crop, focused_crop, eased)
    screen = lerp_rect(rest_screen, focused_screen, eased)

    # "visibility" of the window card -- how much background is showing.
    # At progress=0 the card is small (visibility 1.0).  At progress=1
    # the card fills the frame (visibility 0.0).
    visibility = 1.0 - eased

    return WindowTransform(crop=crop, screen=screen, visibility=visibility)


def screen_point_for_cursor(
    cursor: Point,
    transform: WindowTransform,
    params: WindowParams,
) -> Point:
    """Convert a cursor position expressed in *source screenshot*
    coordinates into *output frame* coordinates given the current
    window transform.  The cursor lives in screenshot space so it can
    track UI elements as the window zooms; this maps it back onto the
    final composited frame."""
    if transform.crop.width <= 0 or transform.crop.height <= 0:
        return Point(cursor.x, cursor.y)

    scale_x = transform.screen.width / transform.crop.width
    scale_y = transform.screen.height / transform.crop.height

    return Point(
        transform.screen.x + (cursor.x - transform.crop.x) * scale_x,
        transform.screen.y + (cursor.y - transform.crop.y) * scale_y,
    )