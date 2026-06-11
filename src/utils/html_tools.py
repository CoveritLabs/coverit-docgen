import re
import math
import copy
from bs4 import Tag, NavigableString
from src.services.labeling.constants import KEEP_ATTRS, INTERACTIVE_TAGS


def is_readable(text: str) -> bool:
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
    return (
        box["x"] + box["width"] / 2,
        box["y"] + box["height"] / 2,
    )


def get_direction(dx: float, dy: float) -> str:
    angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    directions = [
        ("right", 337.5, 360),
        ("right", 0, 22.5),
        ("bottom-right", 22.5, 67.5),
        ("bottom", 67.5, 112.5),
        ("bottom-left", 112.5, 157.5),
        ("left", 157.5, 202.5),
        ("top-left", 202.5, 247.5),
        ("top", 247.5, 292.5),
        ("top-right", 292.5, 337.5),
    ]
    for direction, start, end in directions:
        if start <= angle < end:
            return direction
    return "unknown"


def is_interactive(tag: Tag) -> bool:
    return isinstance(tag, Tag) and (
        tag.name in INTERACTIVE_TAGS or tag.get("role") or tag.get("onclick")
    )


def clean_element(el: Tag) -> str:
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


def get_input_value(el):
    if el is None or isinstance(el, NavigableString):
        return None
    val = el.get("value", "")
    if isinstance(val, str):
        val = val.strip()
        if val and is_readable(val):
            return val
    return None


def get_select_value(el):
    """Get the selected option's text from a <select> element."""
    if el is None or not isinstance(el, Tag):
        return None
    selected = el.find("option", selected=True)
    if selected:
        text = selected.get_text(strip=True)
        if text and is_readable(text):
            return text
    # Fallback: first option
    first = el.find("option")
    if first:
        text = first.get_text(strip=True)
        if text and is_readable(text):
            return text
    return None
