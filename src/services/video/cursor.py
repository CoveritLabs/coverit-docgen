import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ASSET_DIR = Path(__file__).resolve().parent / "assets"


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

    def resolve(self) -> tuple[Path | None, tuple[int, int]]:
        cursor = self.manifest().get("pointer")
        if not cursor:
            return None, (0, 0)

        file_path = self.asset_dir / "cursors" / cursor["file"]
        hotspot = cursor.get("hotspot", [0, 0])
        if not file_path.exists():
            return None, (0, 0)
        return file_path, (int(hotspot[0]), int(hotspot[1]))


def load_cursor_image():
    """Return a Pillow image and hotspot for the configured cursor."""

    from PIL import Image, ImageDraw

    path, hotspot = CursorLibrary().resolve()
    if path is not None:
        return Image.open(path).convert("RGBA"), hotspot

    image = Image.new("RGBA", (28, 36), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fill = (22, 24, 29, 255)
    outline = (255, 255, 255, 255)
    points = [(2, 2), (2, 30), (10, 23), (15, 34), (21, 31), (16, 21), (26, 21)]
    draw.polygon(points, fill=fill, outline=outline)
    return image, (2, 2)