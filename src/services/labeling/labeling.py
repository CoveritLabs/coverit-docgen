import math

from bs4 import NavigableString, Tag, Comment
from src.utils.html_tools import (
    is_readable,
    is_interactive,
    center,
    get_bbox,
)
from src.services.labeling.constants import MAX_DEPTH, NAME_ATTRS
from src.core.config import get_settings

settings = get_settings()


class Labeling:

    @staticmethod
    def _validate(el):
        if el is None:
            raise ValueError("el cannot be None")

        if not isinstance(el, Tag):
            raise TypeError(f"Expected BeautifulSoup Tag, got {type(el).__name__}")

    @staticmethod
    def get_name_from_attrs(el: Tag) -> str | None:
        """
        Extracts a human-readable name from a prioritized list of HTML attributes.
        Iterates through NAME_ATTRS (e.g., 'aria-label', 'title', 'alt') and returns
        the first valid, readable text value encountered.

        Args:
            el Tag: The BeautifulSoup HTML element to inspect.

        Returns:
            The extracted text if it is considered readable by
            `is_readable()`, otherwise None.
        """
        Labeling._validate(el)

        for attr in NAME_ATTRS:
            val = el.get(attr)
            if val and isinstance(val, str):
                clean_val = val.strip()
                if clean_val and is_readable(clean_val):
                    return clean_val

        return None

    @staticmethod
    def get_name_from_text(el: Tag) -> str | None:
        """
        Extract readable text content from an element and its descendants.

        Args:
            el: BeautifulSoup element to extract text from.

        Returns:
            The extracted text if it is considered readable by
            `is_readable()`, otherwise None.
        """
        Labeling._validate(el)

        seen: list[str] = []

        for text in el.strings:
            text = text.strip()

            if text and (not seen or seen[-1] != text):
                seen.append(text)

        result = " ".join(seen).strip()

        return result if is_readable(result) else None

    @staticmethod
    def get_name_from_label(el: Tag) -> str | None:
        """
        Extract the text of a label associated with an element.

        The function first checks whether the element is nested inside
        a <label> ancestor. If no enclosing label is found, it looks
        for a separate <label> element whose `for` attribute matches
        the element's id.

        Args:
            el: BeautifulSoup element.

        Returns:
            The associated label text if found and considered readable,
            otherwise None.
        """
        Labeling._validate(el)

        parent = el.parent
        depth = 0

        # Wrapped label
        while parent and depth < MAX_DEPTH:
            if parent.name == "label":
                text = "".join(
                    s for s in parent.strings if not isinstance(s, Comment)
                ).strip()

                if text and is_readable(text):
                    return text

            parent = parent.parent
            depth += 1

        # 'for' attribute
        search_query = el.get("id", "")
        if not search_query:
            return None

        root = el.find_parent("body") or el.find_parent("html") or el

        label = root.find("label", attrs={"for": search_query})

        if label:
            text = "".join(
                s for s in label.strings if not isinstance(s, Comment)
            ).strip()

            if text and is_readable(text):
                return text

        return None

    @staticmethod
    def get_name_from_children(el: Tag) -> str | None:
        """
        Extract a name from an element's descendants.

        The function searches descendant elements for meaningful text or
        accessibility metadata. It first checks SVG icons for a <title>
        element, then looks for readable text directly owned by a descendant,
        and finally falls back to attribute-based naming via
        `get_name_from_attrs()`.

        Args:
            el: BeautifulSoup element to inspect.

        Returns:
            The first readable name found among the element's descendants,
            or None if no suitable name can be determined.
        """
        Labeling._validate(el)

        for child in el.descendants:
            if isinstance(child, (Comment, NavigableString)):
                continue

            if child.name == "svg":
                svg_title = child.find("title")

                if svg_title:
                    title_text = svg_title.get_text(strip=True)

                    if is_readable(title_text):
                        return title_text

            direct_text = "".join(
                text.strip()
                for text in child.strings
                if text.parent == child and not isinstance(text, Comment)
            ).strip()

            if direct_text and is_readable(direct_text):
                return direct_text

            if name := Labeling.get_name_from_attrs(child):
                return name

        return None

    def _get_candidate_name(self, tag):
        """
        Extract a readable name candidate from a visual element.

        Text nodes contribute their text directly. HTML elements
        contribute either accessibility attributes or visible text.

        Returns:
            A dictionary containing:
                - text: candidate label
                - type: semantic element type

            Or None if no usable label can be derived.
        """
        if isinstance(tag, NavigableString):
            t = tag.strip()
            if t and is_readable(t):
                return {"text": t, "type": "text"}
            return None

        if not isinstance(tag, Tag) or isinstance(tag, Comment):
            return None

        if is_interactive(tag):
            name = self.get_name_from_attrs(tag) or self.get_name_from_text(tag)
        else:
            name = self.get_name_from_text(tag)

        if name and is_readable(name):
            return {"text": name, "type": tag.get("role") or tag.name or "text"}

        return None

    def _get_name_from_context(self, el: Tag, root: Tag) -> str | None:
        """Describe an unnamed element by nearby context or screen position.

        Args:
            el: Target element with ``data-x``, ``data-y``, ``data-width``,
                and ``data-height`` pixel metadata.
            root: Page root containing other visual elements and, when
                available, the screen bounding box.

        Returns:
            A relative description such as ``above the button 'Submit'`` when
            the nearest meaningful neighbor is no more than 40% of the screen
            width and height away. Otherwise returns an absolute description
            based on normalized coordinates from 0.0 to 1.0. The regions use
            thirds and produce top-left, top-center, top-right, left-center,
            center, right-center, bottom-left, bottom-center, or bottom-right
            wording. Returns ``None`` only when the target has no geometry.

        Examples:
            ``to the right of the input 'Search'``
            ``in the bottom-right corner``
            ``centered on the screen``
        """

        self._validate(el)

        target_box = get_bbox(el)

        if not target_box:
            return None

        tx, ty = center(target_box)
        visual_boxes = [
            box
            for tag in [root, *root.find_all(True)]
            if (box := get_bbox(tag)) and box["width"] > 0 and box["height"] > 0
        ]
        if not visual_boxes:
            return None

        root_box = get_bbox(root)
        if not root_box or root_box["width"] <= 0 or root_box["height"] <= 0:
            min_x = min(box["x"] for box in visual_boxes)
            min_y = min(box["y"] for box in visual_boxes)
            max_x = max(box["x"] + box["width"] for box in visual_boxes)
            max_y = max(box["y"] + box["height"] for box in visual_boxes)
            root_box = {
                "x": min_x,
                "y": min_y,
                "width": max(max_x - min_x, target_box["width"], 1.0),
                "height": max(max_y - min_y, target_box["height"], 1.0),
            }

        best = None
        best_score = float("inf")

        for other in root.find_all(True):
            if other == el:
                continue

            if other in el.parents:
                continue

            if isinstance(other, Tag) and el in other.parents:
                continue

            candidate = self._get_candidate_name(other)

            if not candidate:
                continue

            box = get_bbox(other)

            if not box:
                continue

            if box["width"] <= 0 or box["height"] <= 0:
                continue

            ox, oy = center(box)

            dx = tx - ox
            dy = ty - oy

            distance = math.sqrt(dx * dx + dy * dy)

            # slight preference for aligned elements
            alignment_penalty = min(abs(dx), abs(dy)) * 0.2

            score = distance + alignment_penalty

            if score < best_score:
                best_score = score

                best = {
                    "text": candidate["text"],
                    "type": candidate["type"],
                    "dx": dx,
                    "dy": dy,
                }

        if best:
            normalized_dx = abs(best["dx"]) / root_box["width"]
            normalized_dy = abs(best["dy"]) / root_box["height"]
            if max(normalized_dx, normalized_dy) <= settings.context_distance_threshold:
                direction = self._relative_direction(best["dx"], best["dy"])
                return f"{direction} the {best['type']} '{best['text']}'"

        normalized_x = min(1.0, max(0.0, (tx - root_box["x"]) / root_box["width"]))
        normalized_y = min(1.0, max(0.0, (ty - root_box["y"]) / root_box["height"]))
        return self._absolute_screen_position(normalized_x, normalized_y)

    @staticmethod
    def _relative_direction(dx: float, dy: float) -> str:
        """Return natural relative wording for a target-to-neighbor offset."""
        horizontal = "to the right of" if dx > 0 else "to the left of"
        vertical = "below" if dy > 0 else "above"
        if abs(dx) > abs(dy) * 1.5:
            return horizontal
        if abs(dy) > abs(dx) * 1.5:
            return vertical
        return f"{vertical} and {horizontal}"

    @staticmethod
    def _absolute_screen_position(x: float, y: float) -> str:
        """Map normalized center coordinates to one of nine screen regions."""
        horizontal = "left" if x < 0.33 else "right" if x > 0.67 else "center"
        vertical = "top" if y < 0.33 else "bottom" if y > 0.67 else "center"
        region = f"{vertical}-{horizontal}"

        descriptions = {
            "top-left": "in the top-left corner",
            "top-center": "at the top of the screen",
            "top-right": "in the top-right corner",
            "center-left": "on the left side of the screen",
            "center-center": "centered on the screen",
            "center-right": "on the right side of the screen",
            "bottom-left": "in the bottom-left corner",
            "bottom-center": "at the bottom of the screen",
            "bottom-right": "in the bottom-right corner",
        }
        return descriptions[region]

    def get_element_name(self, el: Tag, root: Tag) -> str | None:
        """
        Resolve the most descriptive name for an element.

        The method evaluates multiple naming strategies in priority
        order, including labels, accessibility attributes, visible
        text, descendant content, and finally visual context.

        Args:
            el: Target HTML element.
            root: Page root containing elements with visual bounding-box metadata.

        Returns:
            A human-readable name or None if no name can be determined.
        """
        Labeling._validate(el)

        order = [Labeling.get_name_from_text, Labeling.get_name_from_children]

        if el.name in ("input", "textarea", "select"):
            if name := Labeling.get_name_from_label(el):
                return name
            order.pop(0)

        order.insert((el.name == "a") * len(order), Labeling.get_name_from_attrs)

        for fn in order:
            if name := fn(el):
                return name

        return self._get_name_from_context(el, root)
