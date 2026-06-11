from bs4 import BeautifulSoup
from src.models.graph import (
    CrawlerState,
    CrawlerTransition,
    LabeledElement,
    LabeledState,
)
from src.utils.html_tools import clean_element
from src.services.labeling.page_analyzer import get_page_info
from src.services.labeling.labeling import Labeling
from src.services.labeling.actions import ActionDescription


def label_crawler_state(state: CrawlerState) -> LabeledState:
    """Labels a single Crawler State (Page level information)."""
    soup = BeautifulSoup(state.html, "html.parser")
    page_info = get_page_info(state.url, soup)

    return LabeledState(
        state_id=state.id,
        name=page_info.get("name"),
        description=page_info.get("description"),
    )


def label_crawler_transition(transition: CrawlerTransition) -> LabeledElement:
    state = transition.from_state
    soup = BeautifulSoup(state.html, "html.parser")
    descriptor = ActionDescription()
    labeler = Labeling()

    pressed_element_id = str(transition.pressed_element.id)
    bs4_element = soup.find(attrs={"data-doc-id": pressed_element_id})

    if not bs4_element:
        return LabeledElement(
            element_id=pressed_element_id,
            html_snippet="",
            name="Unknown",
            action="Element not found",
        )

    bbox_lookup = {str(v.id): v.bbox.model_dump() for v in state.visual_elements}

    mapped_visual_elements = []
    for el in soup.find_all(attrs={"data-doc-id": True}):
        current_id = el.get("data-doc-id")
        bbox_data = bbox_lookup.get(current_id)
        mapped_visual_elements.append({"element": el, "bbox": bbox_data})

    name = labeler.get_element_name(bs4_element, mapped_visual_elements)
    action = descriptor.get_action_description(bs4_element, name)

    return LabeledElement(
        element_id=pressed_element_id,
        html_snippet=clean_element(bs4_element),
        name=name,
        action=action,
    )
