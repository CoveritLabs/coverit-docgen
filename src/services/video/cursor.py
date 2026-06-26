import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal


ASSET_DIR = Path(__file__).resolve().parent / "assets"
CursorKind = Literal["default", "hand", "text"]


class CursorLibrary:
    """Loads cursor skins from the video asset manifest."""

    def __init__(self, asset_dir: Path | None = None):
        self.asset_dir = asset_dir or ASSET_DIR
        self.manifest_path = self.asset_dir / "cursors" / "manifest.json"

    @lru_cache(maxsize=1)
    def manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def resolve(
        self,
        cursor_kind: CursorKind = "default",
    ) -> tuple[Path | None, tuple[int, int]]:
        manifest = self.manifest()
        cursor = manifest.get(cursor_kind)
        if cursor is None and cursor_kind == "default":
            cursor = manifest.get("pointer")
        if not cursor:
            return None, (0, 0)

        file_path = self.asset_dir / "cursors" / cursor["file"]
        hotspot = cursor.get("hotspot", [0, 0])
        if not file_path.exists():
            return None, (0, 0)
        return file_path, (int(hotspot[0]), int(hotspot[1]))


def load_cursor_image(cursor_kind: CursorKind = "default"):
    """Return a Pillow image and hotspot for the configured cursor."""

    from PIL import Image

    path, hotspot = CursorLibrary().resolve(cursor_kind)
    if path is not None:
        return Image.open(path).convert("RGBA"), hotspot

    return _fallback_cursor_image(cursor_kind)


def _fallback_cursor_image(cursor_kind: CursorKind):
    from PIL import Image, ImageDraw

    if cursor_kind == "text":
        image = Image.new("RGBA", (18, 34), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        fill = (22, 24, 29, 255)
        outline = (255, 255, 255, 255)
        draw.line((9, 3, 9, 31), fill=outline, width=5)
        draw.line((5, 3, 13, 3), fill=outline, width=5)
        draw.line((5, 31, 13, 31), fill=outline, width=5)
        draw.line((9, 3, 9, 31), fill=fill, width=2)
        draw.line((5, 3, 13, 3), fill=fill, width=2)
        draw.line((5, 31, 13, 31), fill=fill, width=2)
        return image, (9, 17)

    if cursor_kind == "hand":
        image = Image.new("RGBA", (30, 34), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        outline = (255, 255, 255, 255)
        fill = (22, 24, 29, 255)
        points = [
            (12, 2),
            (17, 2),
            (17, 12),
            (20, 10),
            (24, 13),
            (24, 24),
            (19, 32),
            (9, 32),
            (4, 24),
            (4, 17),
            (8, 17),
            (8, 22),
            (12, 22),
        ]
        draw.polygon(points, fill=outline)
        inner = [(x + 1, y + 1) for x, y in points]
        draw.polygon(inner, fill=fill)
        return image, (14, 4)

    image = Image.new("RGBA", (28, 36), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fill = (22, 24, 29, 255)
    outline = (255, 255, 255, 255)
    points = [(2, 2), (2, 30), (10, 23), (15, 34), (21, 31), (16, 21), (26, 21)]
    draw.polygon(points, fill=fill, outline=outline)
    return image, (2, 2)
