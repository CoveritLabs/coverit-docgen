import uuid
from typing import Dict
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from src.models.graph import (
    CrawlerState,
    CrawlerTransition,
    LabeledTransition,
    LabeledState,
    CrawlerGraph,
    LabeledGraph,
)
from src.utils.html_tools import clean_element
from src.services.labeling.page_analyzer import get_page_info
from src.services.labeling.labeling import Labeling
from src.services.labeling.actions import ActionDescription


async def handle_locator(html: str, locator: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        
        element = page.locator(locator).first

        unique_id = f"pw-bridge-{uuid.uuid4().hex[:8]}"
        
        await element.evaluate(
            f'(node) => node.setAttribute("data-pw-locator", "{unique_id}")'
        )
        modified_html = await page.content()
        await browser.close()
        
    return modified_html, unique_id


def label_crawler_state(state: CrawlerState) -> LabeledState:
    """Labels a single Crawler State (Page level information)."""
    soup = BeautifulSoup(state.html, "html.parser")
    page_info = get_page_info(state.url, soup)
    return LabeledState(
        id=state.id,
        name=page_info["name"] or "Unknown",
        description=page_info["description"] or "Unknown",
    )


def label_crawler_transition(
    transition: CrawlerTransition, from_state: CrawlerState
) -> LabeledTransition:
    """
    Labels a transition edge. Takes the transition ID mappings and the origin
    state to resolve the HTML and visual elements.
    """
    descriptor = ActionDescription()
    labeler = Labeling()
    element = None
    if from_state.html:
        modified_html, element_id = handle_locator(from_state.html, transition.locator)
        soup = BeautifulSoup(modified_html, "html.parser")
        element = soup.find(attrs={"data-pw-locator": element_id})

    if not element:
        return LabeledTransition(
            id=transition.id,
            html_snippet="",
            name="Unknown",
            action="Element not found",
        )

    name = labeler.get_element_name(element, soup.html) or "Unknown"
    action = descriptor.get_action_description(element, name) or "Unknown"

    return LabeledTransition(
        id=transition.id,
        html_snippet=clean_element(element),
        name=name,
        action=action,
    )


def label_crawler_graph(graph: CrawlerGraph) -> LabeledGraph:
    """
    Traverses an entire CrawlerGraph, labeling all structural states and
    navigational transitions, and returns a compiled LabeledGraph.

    Args:
        graph (CrawlerGraph): The raw topological graph from the crawler.

    Returns:
        LabeledGraph: The enriched graph pairing raw structure with semantic labels.
    """
    state_labels: Dict[str, LabeledState] = {}
    transition_labels: Dict[str, LabeledTransition] = {}

    for state_id, state in graph.states.items():
        state_labels[state_id] = label_crawler_state(state)

    for transition in graph.transitions:
        from_state = graph.states.get(transition.from_state_id)

        if not from_state:
            continue

        labeled_trans = label_crawler_transition(transition, from_state)
        transition_labels[transition.id] = labeled_trans

    return LabeledGraph(
        session_id=graph.session_id,
        crawler_graph=graph,
        state_labels=state_labels,
        transition_labels=transition_labels,
    )
