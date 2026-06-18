import re
import math
import copy
from bs4 import Tag, NavigableString
from src.services.labeling.constants import KEEP_ATTRS, INTERACTIVE_TAGS, DIRECTION_RANGES


def is_readable(text: str) -> bool:
    """
    Check whether a text string is suitable for use as a human-readable label.
    """
    if not text or len(text.strip()) == 0:
        return False
    text = text.strip()
    if len(text) > 40:
        return False
    if re.match(r"^[a-z0-9_-]+$", text) and ("_" in text or "-" in text):
        return False
    if re.match(r"^[A-Z0-9_]+$", text):
        return False
    if not re.search(r"[a-zA-Z]", text):
        return False

    # filter CSS/code
    if "{" in text or "}" in text:
        return False
    if ";" in text and ":" in text:
        return False

    # filter if special characters dominate
    letters = sum(1 for c in text if c.isalpha() or c.isspace())
    if len(text) > 5 and letters / len(text) < 0.5:
        return False

    return True


def center(box: dict) -> tuple:
    """
    Calculate the center point of a bounding box.
    """
    return (
        box["x"] + box["width"] / 2,
        box["y"] + box["height"] / 2,
    )


def get_direction(dx: float, dy: float) -> str:
    """
    Convert a vector offset into a cardinal or intercardinal direction.
    """
    angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    for direction, start, end in DIRECTION_RANGES:
        if start <= angle < end:
            return direction
    return "unknown"


def is_interactive(tag: Tag) -> bool:
    """
    Determine whether an HTML element is interactive.
    """
    return isinstance(tag, Tag) and (
        tag.name in INTERACTIVE_TAGS or tag.get("role") or tag.get("onclick")
    )


def clean_element(el: Tag) -> str:
    """
    Remove non-essential attributes from an element and its descendants.
    """
    el_copy = copy.copy(el)

    def clean_tag(tag):
        if not isinstance(tag, Tag):
            return
        attrs_to_remove = [attr for attr in tag.attrs if attr not in KEEP_ATTRS]
        for attr in attrs_to_remove:
            del tag[attr]
        for child in tag.children:
            clean_tag(child)

    clean_tag(el_copy)
    return str(el_copy)

def get_bbox(tag):
    try:
        return {
            "x": float(tag["data-x"]),
            "y": float(tag["data-y"]),
            "width": float(tag["data-width"]),
            "height": float(tag["data-height"]),
        }
    except (KeyError, ValueError):
        return None