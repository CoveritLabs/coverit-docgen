from bs4 import NavigableString, Tag
from src.services.labeling.constants import TEXT_INPUT_TYPES
from src.utils.html_tools import is_readable
from src.services.labeling.naming import get_name_from_text


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


def get_action_description(el, name):
    if not name:
        return None

    tag = el.name.lower()
    el_type = (el.get("type", "") or "").lower()
    role = (el.get("role", "") or "").lower()

    in_nav = any(p.name == "nav" for p in el.parents if p and p.name)
    has_img = el.find("img") is not None if isinstance(el, Tag) else False

    has_text = False
    if isinstance(el, Tag):
        for s in el.stripped_strings:
            if is_readable(s):
                has_text = True
                break

    if tag == "a":
        if has_img and not has_text:
            return f'Click on image "{name}"'
        if in_nav:
            return f'Navigate to "{name}"'
        return f'Go to "{name}"'

    if tag == "button" or role == "button" or el_type in ("submit", "button"):
        if has_img and not has_text:
            return f'Click on image "{name}"'
        return f'Click "{name}"'

    if tag == "input" and el_type in TEXT_INPUT_TYPES:
        value = get_input_value(el)
        field_name = name
        if value and field_name:
            if el_type == "search":
                return f'Search for "{value}" in "{field_name}"'
            return f'Enter "{value}" in "{field_name}"'
        if value:
            if el_type == "search":
                return f'Search for "{value}"'
            return f'Enter "{value}"'
        if field_name:
            if el_type == "search":
                return f'Search "{field_name}"'
            return f'Enter "{field_name}"'
        return f'Enter "{name}"'

    if tag == "input":
        if el_type == "checkbox":
            return f'Toggle "{name}"'
        if el_type == "radio":
            return f'Select "{name}"'
        if el_type == "file":
            return f'Upload "{name}"'
        return f'Enter "{name}"'

    if tag == "textarea":
        value = get_name_from_text(el)
        field_name = name
        if value and field_name:
            return f'Type "{value}" in "{field_name}"'
        if value:
            return f'Type "{value}"'
        if field_name:
            return f'Type in "{field_name}"'
        return f'Type in "{name}"'

    if tag == "select":
        value = get_select_value(el)
        if value and name:
            return f'Select "{value}" from "{name}"'
        if value:
            return f'Select "{value}"'
        return f'Select from "{name}"'

    if role == "tab":
        return f'Switch to "{name}" tab'
    if role == "menuitem":
        return f'Click on "{name}" menu item'
    if role in ("switch", "checkbox"):
        return f'Toggle "{name}"'
    if role in ("radio", "option"):
        return f'Select "{name}"'
    if role == "link":
        return f'Go to "{name}"'

    if has_img and not has_text:
        return f'Click on image "{name}"'
    return f'Click "{name}"'
