import math
from bs4 import NavigableString, Tag, Comment
from src.utils.html_tools import is_readable, is_interactive, center, get_direction
from src.services.labeling.constants import MAX_DEPTH


def get_name_from_attrs(el):
    if el is None or isinstance(el, NavigableString):
        return None
    attrs = ("aria-label", "title", "alt", "placeholder", "name")
    for attr in attrs:
        val = el.get(attr, "")
        if isinstance(val, str):
            val = val.strip()
            if val and is_readable(val):
                return val
    return None


def get_name_from_text(el):
    if el is None or isinstance(el, NavigableString):
        return None
    seen = []
    for child in el.descendants:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            t = child.strip()
            if t and (not seen or seen[-1] != t):
                seen.append(t)
    text = " ".join(seen).strip()
    return text if is_readable(text) else None


def get_name_from_label(el):
    if el is None or isinstance(el, NavigableString):
        return None
    parent = el.parent
    depth = 0
    while parent and depth < MAX_DEPTH:
        if parent.name == "label":
            t = "".join(s for s in parent.strings if not isinstance(s, Comment)).strip()
            if t and is_readable(t):
                return t
        parent = parent.parent
        depth += 1

    root = el.find_parent("[id]") or el.find_parent("body") or el.find_parent("html")
    search_query = el.get("id", "") or el.get("name", "")
    if search_query:
        label = root.find("label", attrs={"for": search_query})
        if label:
            t = "".join(s for s in label.strings if not isinstance(s, Comment)).strip()
            if t and is_readable(t):
                return t
    return None


def get_name_from_children(el):
    if el is None or isinstance(el, NavigableString):
        return None
    for child in el.descendants:
        if isinstance(child, Comment) or isinstance(child, NavigableString):
            continue
        if child.name == "svg":
            svg_title = child.find("title")
            if svg_title and is_readable(svg_title.get_text(strip=True)):
                return svg_title.get_text(strip=True)

        direct_text = "".join(
            s.strip()
            for s in child.strings
            if s.parent == child and not isinstance(s, Comment)
        ).strip()
        if direct_text and is_readable(direct_text):
            return direct_text
        if name := get_name_from_attrs(child):
            return name
    return None


def get_name_from_context(el, visual_elements):
    if el is None or isinstance(el, NavigableString):
        return None

    def get_candidate_name(tag):
        # 6. Explicitly ignore comment nodes from context identification
        if isinstance(tag, Comment):
            return None

        # text node case
        if isinstance(tag, NavigableString):
            t = tag.strip()
            if t and is_readable(t):
                return {"text": t, "type": "text"}
            return None

        if not isinstance(tag, Tag):
            return None

        # interactive element
        if is_interactive(tag):
            name = get_name_from_attrs(tag) or get_name_from_text(tag)

            if name and is_readable(name):
                return {"text": name, "type": tag.get("role") or tag.name}

        # regular readable text element
        text = get_name_from_text(tag)

        if text and is_readable(text):
            return {"text": text, "type": "text"}

        return None

    # -----------------------------
    # locate target bbox
    # -----------------------------

    target_data = None

    for item in visual_elements:
        if item["element"] == el:
            target_data = item
            break

    if not target_data:
        return None

    target_box = target_data["bbox"]
    tx, ty = center(target_box)

    # -----------------------------
    # find closest visual neighbor
    # -----------------------------

    best = None
    best_score = float("inf")

    for item in visual_elements:
        other = item["element"]

        if other == el:
            continue

        if other in el.parents:
            continue

        candidate = get_candidate_name(other)

        if not candidate:
            continue

        box = item["bbox"]

        if box["width"] <= 0 or box["height"] <= 0:
            continue

        ox, oy = center(box)

        dx = ox - tx
        dy = oy - ty

        distance = math.sqrt(dx * dx + dy * dy)

        # slight preference for aligned elements
        alignment_penalty = min(abs(dx), abs(dy)) * 0.2

        score = distance + alignment_penalty

        if score < best_score:
            best_score = score

            best = {
                "text": candidate["text"],
                "type": candidate["type"],
                "direction": get_direction(dx, dy),
            }

    if not best:
        return None

    # invert direction because we describe
    # target relative to neighbor
    reverse_direction = {
        "left": "right",
        "right": "left",
        "top": "bottom",
        "bottom": "top",
        "top-left": "bottom-right",
        "top-right": "bottom-left",
        "bottom-left": "top-right",
        "bottom-right": "top-left",
    }

    direction = reverse_direction[best["direction"]]

    return f"element to the {direction} " f"of the {best['type']} " f"'{best['text']}'"


def get_element_name(el, visual_elements):
    if el is None or isinstance(el, NavigableString):
        return None
    order = [get_name_from_text, get_name_from_children]
    if el.name in ("input", "textarea", "select"):
        if name := get_name_from_label(el):
            return name
        order.pop(0)
    order.insert((el.name == "a") * len(order), get_name_from_attrs)
    for fn in order:
        if name := fn(el):
            return name
    if contextual_name := get_name_from_context(el, visual_elements):
        return contextual_name
    return None
