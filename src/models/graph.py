from pydantic import BaseModel
from typing import Optional, List


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class VisualElement(BaseModel):
    id: str  # Maps to data-doc-id in the HTML
    bbox: BoundingBox


class CrawlerState(BaseModel):
    id: str
    url: str
    html: str
    visual_elements: List[VisualElement]


class CrawlerTransition(BaseModel):
    from_state: CrawlerState
    to_state: CrawlerState
    pressed_element: VisualElement


class LabeledElement(BaseModel):
    element_id: str
    html_snippet: str
    name: Optional[str]
    action: Optional[str]


class LabeledState(BaseModel):
    state_id: str
    name: Optional[str]
    description: Optional[str]
