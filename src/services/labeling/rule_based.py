import uuid
from typing import Dict

from bs4 import BeautifulSoup

from src.core.playwright import playwright_manager
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
    """Resolve and mark a Playwright locator in an HTML snapshot."""

    return await playwright_manager.resolve_locator(html, locator)


def label_crawler_state(state: CrawlerState) -> LabeledState:
    """Create a page-level label for one crawler state."""
    soup = BeautifulSoup(state.html, "html.parser")
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

    async def get_element(locator: str):
        modified_html, element_id = await handle_locator(from_state.html, locator)
        soup = BeautifulSoup(modified_html, "html.parser")
        element = soup.find(attrs={"data-pw-locator": element_id})
        if element is None:
            raise ValueError("Marked transition element was not found in parsed HTML")
        return element, soup

    def resolve_action_value(action_type: str, value: str | None, element):
        """Normalize the raw action value for description generation."""

        if not value or not value.strip():
            return None

        if action_type == "select":
            option_tag = element.find("option", value=value)
            option_text = option_tag and option_tag.get_text(strip=True)
            return option_text or value

        return value

    labeler = Labeling()
    action_describer = ActionDescription()
    action_parts: list[str] = []
    last_element = None
    last_name = None

    action_values = transition.action_value or [{"s": transition.locator, "t": "", "v": None}]

    for action in action_values:
        element, soup = await get_element(action["s"])
        last_element = element

        name = labeler.get_element_name(element, soup.html or soup)
        if not name or not name.strip():
            raise ValueError("Transition element produced an empty label")

        last_name = name
        resolved_value = resolve_action_value(action["t"], action.get("v"), element)
        action_parts.append(
            action_describer.get_action_description(element, name, resolved_value)
        )

    full_action = " then ".join(action_parts).strip()
    if not full_action:
        raise ValueError("Transition element produced an empty action")

    return LabeledTransition(
        id=transition.id,
        html_snippet=clean_element(last_element),
        name=last_name,
        action=full_action,
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
