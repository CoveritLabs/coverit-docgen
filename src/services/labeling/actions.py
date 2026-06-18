from dataclasses import dataclass
from typing import Optional
from bs4 import Tag
from src.services.labeling.constants import TEXT_INPUT_TYPES
from src.services.labeling.labeling import Labeling
from src.utils.html_tools import is_readable


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
    value: Optional[str]


class ActionDescription:
    """Generates human-readable action descriptions for HTML elements."""

    INPUT_MAP = {
        "submit": lambda name: f'Press "{name}"',
        "checkbox": lambda name: f'Toggle "{name}"',
        "switch": lambda name: f'Toggle "{name}"',
        "radio": lambda name: f'Select "{name}"',
        "option": lambda name: f'Select "{name}"',
        "file": lambda name: f'Upload a file for "{name}"',
        "tab": lambda name: f'Switch to "{name}" tab',
        "menuitem": lambda name: f'Click on "{name}" menu item',
    }

    SITUATION_MAP = {
        "image": lambda name: f'Click on image "{name}"',
        "link": lambda name: f'Click link "{name}"',
        "link_in_nav": lambda name: f'Navigate to "{name}"',
        "button": lambda name: f'Click "{name}" button',
        "input": lambda name: f'Fill out the "{name}" input',
        "select": lambda name: f'Select from "{name}" Filter',
        "textarea": lambda name: f'Type in "{name}"',
        "input_with_value": lambda name, value: f'Fill "{name}" with "{value}"',
        "select_with_value": lambda name, value: f'Select "{value}" from "{name}" Filter',
        "textarea_with_value": lambda name, value: f'Type "{value}" ' f'in "{name}"',
        "FALLBACK": lambda name: f'Click "{name}"',
    }

    def _build_context(self, el: Tag, name: str, value: str | None) -> ActionContext:
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
            value=value,
        )

    def _anchor_description(self, context: ActionContext) -> str:
        if context.image_only:
            return self.SITUATION_MAP["image"](context.name)

        if context.in_nav:
            return self.SITUATION_MAP["link_in_nav"](context.name)

        return self.SITUATION_MAP["link"](context.name)

    def _button_description(self, context: ActionContext) -> str:
        if context.image_only:
            return self.SITUATION_MAP["image"](context.name)

        return self.SITUATION_MAP["button"](context.name)

    def _text_input_description(self, context: ActionContext) -> str:
        if context.value:
            return self.SITUATION_MAP["input_with_value"](context.name, context.value)
        return self.SITUATION_MAP["input"](context.name)

    def _input_description(self, context: ActionContext) -> str:
        if context.el_type in self.INPUT_MAP:
            return self.INPUT_MAP[context.el_type](context.name)
        return self.SITUATION_MAP["input"](context.name)

    def _select_description(self, context: ActionContext) -> str:
        if context.value:
            return self.SITUATION_MAP["select_with_value"](context.name, context.value)
        return self.SITUATION_MAP["select"](context.name)

    def _textarea_description(self, context: ActionContext) -> str:
        if context.value:
            return self.SITUATION_MAP["textarea_with_value"](
                context.name, context.value
            )
        return self.SITUATION_MAP["textarea"](context.name)

    def get_action_description(self, el: Tag, name: str, value: str | None) -> str:
        """Return a human-readable action description for an element."""

        context = self._build_context(el, name, value)

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
            return self.SITUATION_MAP["image"](context.name)

        return self.SITUATION_MAP["FALLBACK"](context.name)
