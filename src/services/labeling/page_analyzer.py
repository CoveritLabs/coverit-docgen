"""Deterministic page-name and description extraction."""

import re
from typing import Dict, Optional
from urllib.parse import parse_qsl, unquote, urlparse

from bs4 import BeautifulSoup, Tag

DESCRIPTION_LIMIT = 160
GENERIC_NAMES = {"home", "welcome", "page", "website", "app", "application"}
IGNORED_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "page",
    "limit",
    "offset",
    "sort",
    "order",
    "token",
    "code",
}
QUERY_LABELS = {"tab": "tab", "section": "section", "view": "view"}
SOURCE_WEIGHTS = {
    "url_path": 60,
    "title": 50,
    "h1": 40,
    "og_title": 30,
    "active_nav": 20,
    "domain": 10,
}


def _normalize_text(value: str | None) -> str | None:
    """Collapse whitespace and return non-empty text."""
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", unquote(value)).strip()
    return normalized or None


def _humanize(value: str) -> str | None:
    """Convert a URL-style token into title-cased human-readable text."""
    value = re.sub(r"[-_]+", " ", unquote(value))
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    normalized = _normalize_text(value)
    return normalized.title() if normalized else None


def _is_opaque_segment(segment: str) -> bool:
    """Return whether a URL segment resembles an ID, UUID, token, or file."""
    value = unquote(segment).strip()
    if not value or value.isdigit():
        return True
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
        value,
    ):
        return True
    if re.fullmatch(r"[0-9a-fA-F]{16,}", value):
        return True
    if len(value) >= 24 and re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
        return True
    if re.search(r"\.[A-Za-z0-9]{2,5}$", value):
        return True
    return False


def _domain_name(parsed) -> str | None:
    """Return a humanized host label without protocol, www, port, or TLD."""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    labels = [label for label in host.split(".") if label]
    if not labels:
        return None
    meaningful = labels[-2] if len(labels) > 1 else labels[0]
    return _humanize(meaningful)


def _extract_url_signals(url: str) -> dict[str, str | None]:
    """Extract semantic path, query, fragment, and domain candidates."""
    parsed = urlparse(url or "")
    path_parts = [
        humanized
        for segment in parsed.path.split("/")
        if segment and not _is_opaque_segment(segment)
        if (humanized := _humanize(segment))
    ]

    suffixes: list[str] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key = key.lower()
        if key in IGNORED_QUERY_KEYS or not value or _is_opaque_segment(value):
            continue
        humanized = _humanize(value)
        if humanized and key in QUERY_LABELS:
            suffixes.append(f"{humanized} {QUERY_LABELS[key]}")

    fragment = parsed.fragment
    if fragment and not _is_opaque_segment(fragment):
        humanized_fragment = _humanize(fragment)
        if humanized_fragment:
            suffixes.append(f"{humanized_fragment} section")

    url_parts = path_parts + suffixes
    return {
        "url_path": " > ".join(url_parts) if url_parts else None,
        "domain": _domain_name(parsed),
    }


def _meta_content(soup: BeautifulSoup, **attrs: str) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    return _normalize_text(tag.get("content")) if isinstance(tag, Tag) else None


def _strip_site_suffix(title: str | None, domain: str | None) -> str | None:
    """Remove a likely site-name suffix from a document title."""
    title = _normalize_text(title)
    if not title:
        return None

    for separator in (" | ", " - ", " — ", " :: "):
        if separator not in title:
            continue
        parts = [part.strip() for part in title.split(separator) if part.strip()]
        if len(parts) < 2:
            continue
        suffix = parts[-1]
        suffix_tokens = _tokens(suffix)
        domain_tokens = _tokens(domain or "")
        organization_markers = {
            "app",
            "company",
            "corporation",
            "corp",
            "inc",
            "labs",
            "limited",
            "llc",
            "platform",
            "software",
        }
        if (
            domain_tokens
            and domain_tokens.issubset(suffix_tokens)
            or suffix_tokens.intersection(organization_markers)
        ):
            return separator.join(parts[:-1])
    return title


def _extract_active_nav(soup: BeautifulSoup) -> str | None:
    """Return readable text from the first explicitly active nav element."""
    selectors = (
        '[aria-current="page"]',
        '[aria-current="true"]',
        "nav .active",
        "nav .selected",
        '[role="navigation"] .active',
        '[role="navigation"] .selected',
    )
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = _normalize_text(element.get_text(" ", strip=True))
            if text:
                return text
    return None


def _extract_html_signals(
    soup: BeautifulSoup, domain: str | None
) -> dict[str, str | None]:
    """Extract cleaned title, heading, metadata, and active-navigation text."""
    title_tag = soup.find("title")
    h1 = soup.find("h1")
    return {
        "title": _strip_site_suffix(
            title_tag.get_text(" ", strip=True) if title_tag else None,
            domain,
        ),
        "h1": _normalize_text(h1.get_text(" ", strip=True)) if h1 else None,
        "og_title": _meta_content(soup, property="og:title")
        or _meta_content(soup, name="og:title"),
        "og_description": _meta_content(soup, property="og:description")
        or _meta_content(soup, name="og:description"),
        "meta_description": _meta_content(soup, name="description"),
        "active_nav": _extract_active_nav(soup),
    }


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1
    }


def _select_page_name(signals: dict[str, str | None]) -> str | None:
    """Select the strongest specific name using source priority and agreement."""
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    populated = [
        value
        for source, value in signals.items()
        if source in SOURCE_WEIGHTS and value
    ]

    for order, (source, weight) in enumerate(SOURCE_WEIGHTS.items()):
        value = signals.get(source)
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        score = weight
        value_tokens = _tokens(value)
        if value.casefold() in GENERIC_NAMES:
            score -= 20
        if source == "url_path" and " > " in value:
            score += 5
        if any(
            value_tokens
            and value_tokens.intersection(_tokens(other))
            for other in populated
            if other != value
        ):
            score += 10
        candidates.append((score, -order, value))

    return max(candidates, default=(0, 0, None))[2]


def _truncate_description(value: str) -> str:
    """Return a single concise sentence no longer than 160 characters."""
    text = _normalize_text(value) or ""
    sentence_match = re.match(r"^(.+?[.!?])(?:\s|$)", text)
    if sentence_match:
        text = sentence_match.group(1)
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    shortened = text[: DESCRIPTION_LIMIT - 1].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{shortened}…"


def _select_page_description(
    signals: dict[str, str | None], name: str | None
) -> str | None:
    """Select metadata first, then non-duplicative heading/navigation context."""
    for source in ("og_description", "meta_description", "h1", "active_nav"):
        value = signals.get(source)
        if not value:
            continue
        if name and _tokens(value) == _tokens(name):
            continue
        return _truncate_description(value)
    return None


def get_page_info(
    url: str, soup: BeautifulSoup
) -> Dict[str, Optional[str]]:
    """Return a deterministic human-readable page name and description.

    Args:
        url: Page URL. Semantic path segments, selected query parameters, and
            fragments are humanized; numeric IDs, UUIDs, files, tokens,
            tracking parameters, pagination, and sorting values are ignored.
        soup: Parsed page snapshot used for title, ``h1``, Open Graph,
            description metadata, and active-navigation signals.

    Returns:
        ``{"name": ..., "description": ...}``. Name selection prioritizes a
        clean URL path, stripped title, ``h1``, Open Graph title, active
        navigation, then domain. Agreement and specificity adjust those fixed
        weights. Description selection prioritizes Open Graph description,
        meta description, then non-duplicative heading or navigation context,
        normalized to one sentence and at most 160 characters.
    """
    url_signals = _extract_url_signals(url)
    signals = {
        **url_signals,
        **_extract_html_signals(soup, url_signals["domain"]),
    }
    name = _select_page_name(signals)
    return {
        "name": name,
        "description": _select_page_description(signals, name),
    }
