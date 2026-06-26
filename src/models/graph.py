from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Set, Any


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class CrawlerState(BaseModel):
    id: str
    url: str
    html: str


class CrawlerTransition(BaseModel):
    id: str
    from_state_id: str
    to_state_id: str
    locator: str
    action_value: List[Dict[str, Any]] = Field(default_factory=list)


class LabeledTransition(BaseModel):
    id: str
    html_snippet: str
    name: Optional[str]
    action: Optional[str]


class LabeledState(BaseModel):
    id: str
    name: Optional[str]
    description: Optional[str]


class CrawlerGraph(BaseModel):
    """
    The complete graph topology of the crawled application.
    """

    graph_id: str
    states: Dict[str, CrawlerState] = Field(
        description="Dictionary mapping state_id to CrawlerState"
    )
    transitions: List[CrawlerTransition] = Field(
        description="List of edges connecting the states"
    )
    skip_states: Set[str] = Field(
        default_factory=set, description="Set of skipped state IDs"
    )


class LabeledGraph(BaseModel):
    """
    Maintains a separation of concerns between raw crawler data and human annotations.
    Ideal for active labeling tools and database storage.
    """

    graph_id: str
    crawler_graph: CrawlerGraph
    state_labels: Dict[str, LabeledState]
    transition_labels: Dict[str, LabeledTransition]
