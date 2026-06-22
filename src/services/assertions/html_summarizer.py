import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from src.utils.html_tools import is_readable

MAX_TEXT_ITEMS = 60
MAX_SELECTORS = 80
VOLATILE_VALUE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
    r"|([0-9a-f]{16,})"
    r"|(\d{4}-\d{2}-\d{2})"
    r"|(\d{1,2}:\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ElementCandidate:
    selector: str
    tag: str
    text: str = ""
    role: str = ""
    input_type: str = ""
    value: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HtmlSummary:
    title: str = ""
    headings: list[str] = field(default_factory=list)
    visible_text: list[str] = field(default_factory=list)
    candidates: list[ElementCandidate] = field(default_factory=list)

    def model_payload(self) -> dict:
        return {
            "title": self.title,
            "headings": self.headings,
            "visibleText": self.visible_text,
            "candidates": [
                {
                    "selector": candidate.selector,
                    "tag": candidate.tag,
                    "text": candidate.text,
                    "role": candidate.role,
                    "inputType": candidate.input_type,
                    "value": candidate.value,
                    "attributes": candidate.attributes,
                }
                for candidate in self.candidates
            ],
        }


def summarize_html(html: str, max_chars: int = 12000) -> HtmlSummary:
    soup = BeautifulSoup((html or "")[:max_chars], "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
    headings = _unique(
        _clean_text(tag.get_text(" ", strip=True))
        for tag in soup.find_all(["h1", "h2", "h3"])[:20]
    )
    text_items = _unique(
        text
        for text in (_clean_text(node) for node in soup.stripped_strings)
        if _is_stable_text(text)
    )[:MAX_TEXT_ITEMS]
    candidates = _candidate_elements(soup)[:MAX_SELECTORS]

    return HtmlSummary(
        title=title,
        headings=headings,
        visible_text=text_items,
        candidates=candidates,
    )


def _candidate_elements(soup: BeautifulSoup) -> list[ElementCandidate]:
    selectors = (
        "[data-testid]",
        "[data-test]",
        "[aria-label]",
        "[role]",
        "button",
        "a",
        "input",
        "textarea",
        "select",
        "form",
        "table",
        "[class]",
        "[id]",
    )
    candidates: list[ElementCandidate] = []
    seen: set[str] = set()
    for tag in soup.select(",".join(selectors)):
        if not isinstance(tag, Tag):
            continue
        selector = _selector_for(tag)
        if not selector or selector in seen:
            continue
        seen.add(selector)
        text = _clean_text(tag.get_text(" ", strip=True))
        value = _clean_text(str(tag.get("value") or ""))
        candidates.append(
            ElementCandidate(
                selector=selector,
                tag=tag.name or "",
                text=text if _is_stable_text(text) else "",
                role=str(tag.get("role") or ""),
                input_type=str(tag.get("type") or ""),
                value=value if _is_stable_text(value) else "",
                attributes=_stable_attributes(tag),
            )
        )
    return candidates


def _selector_for(tag: Tag) -> str:
    for attr in ("data-testid", "data-test", "aria-label", "id"):
        value = _stable_attr_value(tag.get(attr))
        if value:
            if attr == "id":
                return f"#{value}"
            return f'[{attr}="{value}"]'

    classes = [
        value
        for value in tag.get("class", [])
        if isinstance(value, str) and _stable_attr_value(value)
    ]
    if classes:
        return f"{tag.name}.{'.'.join(classes[:2])}"

    role = _stable_attr_value(tag.get("role"))
    if role:
        return f'{tag.name}[role="{role}"]'

    if tag.name in {"button", "input", "textarea", "select", "form", "table"}:
        return tag.name or ""
    return ""


def _stable_attributes(tag: Tag) -> dict[str, str]:
    stable: dict[str, str] = {}
    for attr in ("aria-selected", "aria-checked", "aria-disabled", "disabled", "checked"):
        value = tag.get(attr)
        if value is not None:
            stable[attr] = str(value)
    return stable


def _stable_attr_value(value) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned or VOLATILE_VALUE.search(cleaned):
        return ""
    if len(cleaned) > 80:
        return ""
    return cleaned


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_stable_text(value: str) -> bool:
    return bool(value and is_readable(value) and not VOLATILE_VALUE.search(value))


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        result.append(value)
    return result
