import math
from bs4 import NavigableString, Tag, Comment
from src.utils.html_tools import (
    is_readable,
    is_interactive,
    center,
    get_bbox,
    get_direction,
)
from src.services.labeling.constants import MAX_DEPTH, NAME_ATTRS


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

        name = (
            self.get_name_from_attrs(tag)
            if is_interactive(tag)
            else self.get_name_from_text(tag)
        )

        if name and is_readable(name):
            return {"text": name, "type": tag.get("role") or tag.name or "text"}

        return None

    def _get_name_from_context(self, el: Tag, root: Tag) -> str | None:
        """
        Generate a contextual name using nearby visual elements.

        Uses bounding box attributes stored directly on DOM elements:
            data-x
            data-y
            data-width
            data-height
        """

        self._validate(el)

        target_box = get_bbox(el)

        if not target_box:
            return None

        tx, ty = center(target_box)

        # nearest neighbor
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
                    "direction": get_direction(dx, dy),
                }

        if not best:
            return None

        return (
            f"element to the {best['direction']} "
            f"of the {best['type']} "
            f"'{best['text']}'"
        )

    def get_element_name(self, el: Tag, root: Tag) -> str | None:
        """
        Resolve the most descriptive name for an element.

        The method evaluates multiple naming strategies in priority
        order, including labels, accessibility attributes, visible
        text, descendant content, and finally visual context.

        Args:
            el: Target HTML element.
            visual_elements: Elements with visual bounding-box metadata.

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
