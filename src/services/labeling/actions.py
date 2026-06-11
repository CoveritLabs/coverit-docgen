from dataclasses import dataclass
from typing import Optional
from bs4 import Tag
from src.services.labeling.constants import TEXT_INPUT_TYPES
from src.services.labeling.labeling import Labeling
from src.utils.html_tools import (
    get_input_value,
    get_select_value,
    is_readable,
)


@dataclass(frozen=True)
class ActionContext:
    """Information extracted from an HTML element."""

    el: Tag
    name: str
    tag: str
    el_type: str
    role: str
    in_nav: bool
    image_only: bool
    input_value: Optional[str]
    select_value: Optional[str]
    textarea_value: Optional[str]


class ActionDescription:
    """Generates human-readable action descriptions for HTML elements."""

    INPUT_MAP = {
        "checkbox": lambda name: f'Toggle "{name}"',
        "switch": lambda name: f'Toggle "{name}"',
        "radio": lambda name: f'Select "{name}"',
        "option": lambda name: f'Select "{name}"',
        "link": lambda name: f'Go to "{name}"',
        "file": lambda name: f'Upload "{name}"',
        "tab": lambda name: f'Switch to "{name}" tab',
        "menuitem": lambda name: f'Click on "{name}" menu item',
    }

    def _build_context(self, el: Tag, name: str) -> ActionContext:
        """Build an ActionContext from a BeautifulSoup element."""

        if el is None:
            raise ValueError("el cannot be None")

        if not isinstance(el, Tag):
            raise TypeError(f"Expected BeautifulSoup Tag, got {type(el).__name__}")

        if not isinstance(name, str):
            raise TypeError(f"Expected name to be str, got {type(name).__name__}")

        if not name.strip():
            raise ValueError("name cannot be empty")

        tag = (el.name or "").lower()
        el_type = (el.get("type", "") or "").lower()
        role = (el.get("role", "") or "").lower()

        in_nav = any(
            parent.name == "nav" for parent in el.parents if parent and parent.name
        )

        has_img = el.find("img") is not None
        has_text = any(is_readable(text) for text in el.stripped_strings)

        return ActionContext(
            el=el,
            name=name,
            tag=tag,
            el_type=el_type,
            role=role,
            in_nav=in_nav,
            image_only=has_img and not has_text,
            input_value=get_input_value(el),
            select_value=get_select_value(el),
            textarea_value=Labeling.get_name_from_text(el),
        )

    def _image_description(self, context: ActionContext) -> str:
        return f'Click on image "{context.name}"'

    def _anchor_description(self, context: ActionContext) -> str:
        if context.image_only:
            return self._image_description(context)

        if context.in_nav:
            return f'Navigate to "{context.name}"'

        return f'Go to "{context.name}"'

    def _button_description(self, context: ActionContext) -> str:
        if context.image_only:
            return self._image_description(context)

        return f'Click "{context.name}"'

    def _text_input_description(self, context: ActionContext) -> str:
        if context.input_value:
            if context.el_type == "search":
                return f'Search for "{context.input_value}" ' f'in "{context.name}"'

            return f'Enter "{context.input_value}" ' f'in "{context.name}"'

        if context.el_type == "search":
            return f'Search "{context.name}"'

        return f'Enter "{context.name}"'

    def _input_description(self, context: ActionContext) -> str:
        if context.el_type in self.INPUT_MAP:
            return self.INPUT_MAP[context.el_type](context.name)

        return f'Enter "{context.name}"'

    def _select_description(self, context: ActionContext) -> str:
        if context.select_value:
            return f'Select "{context.select_value}" ' f'from "{context.name}"'

        return f'Select from "{context.name}"'

    def _textarea_description(self, context: ActionContext) -> str:
        if context.textarea_value:
            return f'Type "{context.textarea_value}" ' f'in "{context.name}"'

        return f'Type in "{context.name}"'

    def get_action_description(self, el: Tag, name: str) -> str:
        """Return a human-readable action description for an element."""

        context = self._build_context(el, name)

        if context.tag == "a":
            return self._anchor_description(context)

        if (
            context.tag == "button"
            or context.role == "button"
            or context.el_type in ("submit", "button")
        ):
            return self._button_description(context)

        if context.tag == "input":
            if context.el_type in TEXT_INPUT_TYPES:
                return self._text_input_description(context)

            return self._input_description(context)

        if context.tag == "textarea":
            return self._textarea_description(context)

        if context.tag == "select":
            return self._select_description(context)

        if context.role in self.INPUT_MAP:
            return self.INPUT_MAP[context.role](context.name)

        if context.image_only:
            return self._image_description(context)

        return f'Click "{context.name}"'
