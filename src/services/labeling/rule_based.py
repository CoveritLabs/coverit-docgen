import uuid
from typing import Dict

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from src.models.graph import (
    CrawlerGraph,
    CrawlerState,
    CrawlerTransition,
    LabeledGraph,
    LabeledState,
    LabeledTransition,
)
from src.services.labeling.actions import ActionDescription
from src.services.labeling.labeling import Labeling
from src.services.labeling.page_analyzer import get_page_info
from src.utils.html_tools import clean_element


async def handle_locator(html: str, locator: str) -> tuple[str, str]:
    """Mark the first Playwright locator match and return the updated HTML.

    Args:
        html: Complete origin-page HTML.
        locator: Playwright locator expression for the interacted element.

    Returns:
        A tuple containing serialized HTML and the temporary marker value.

    Raises:
        ValueError: If HTML or locator metadata is missing.
        playwright.async_api.Error: If the locator cannot be evaluated.
    """
    if not html.strip():
        raise ValueError("Origin state HTML is empty")
    if not locator or not locator.strip():
        raise ValueError("Transition locator is empty")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            element = page.locator(locator).first
            if await element.count() == 0:
                raise ValueError(f"Transition locator did not match: {locator}")

            unique_id = f"pw-bridge-{uuid.uuid4().hex[:8]}"
            await element.evaluate(
                "(node, marker) => node.setAttribute(" '"data-pw-locator", marker)',
                unique_id,
            )
            return await page.content(), unique_id
        finally:
            await browser.close()


def label_crawler_state(state: CrawlerState) -> LabeledState:
    """Create a page-level label for one crawler state."""
    soup = BeautifulSoup(state.html or "", "html.parser")
    page_info = get_page_info(state.url, soup)
    return LabeledState(
        id=state.id,
        name=page_info["name"] or "Unknown",
        description=page_info["description"] or "Unknown",
    )


async def label_crawler_transition(
    transition: CrawlerTransition, from_state: CrawlerState
) -> LabeledTransition:
    """Create a semantic label for one transition using its origin page.

    Missing HTML, locator metadata, or locator matches are treated as labeling
    failures so callers can return only that transition to ``PENDING``.
    """
    modified_html, element_id = await handle_locator(
        from_state.html, transition.locator
    )
    soup = BeautifulSoup(modified_html, "html.parser")
    element = soup.find(attrs={"data-pw-locator": element_id})
    if element is None:
        raise ValueError("Marked transition element was not found in parsed HTML")

    labeler = Labeling()
    name = labeler.get_element_name(element, soup.html or soup)
    if not name or not name.strip():
        raise ValueError("Transition element produced an empty label")

    action = ActionDescription().get_action_description(element, name)
    if not action or not action.strip():
        raise ValueError("Transition element produced an empty action")

    return LabeledTransition(
        id=transition.id,
        html_snippet=clean_element(element),
        name=name,
        action=action,
    )


async def label_crawler_graph(graph: CrawlerGraph) -> LabeledGraph:
    """Label all eligible graph records and return the compiled result.

    This helper raises on an item failure. The ARQ graph task performs its own
    per-item loop so it can persist successes and roll back failures separately.
    """
    state_labels: Dict[str, LabeledState] = {}
    transition_labels: Dict[str, LabeledTransition] = {}

    for state_id, state in graph.states.items():
        if state_id not in graph.skip_states:
            state_labels[state_id] = label_crawler_state(state)

    for transition in graph.transitions:
        from_state = graph.states.get(transition.from_state_id)
        if from_state is None:
            raise ValueError(f"Origin state {transition.from_state_id} is unavailable")
        transition_labels[transition.id] = await label_crawler_transition(
            transition, from_state
        )

    return LabeledGraph(
        session_id=graph.session_id,
        crawler_graph=graph,
        state_labels=state_labels,
        transition_labels=transition_labels,
    )
