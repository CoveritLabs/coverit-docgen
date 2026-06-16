from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class StepType(str, Enum):
    STATE = "STATE"
    TRANSITION = "TRANSITION"
    ASSERTION = "ASSERTION"
    ACTION_HOOK = "ACTION_HOOK"


class BddFlowInput(BaseModel):
    checkpoint_hash: str = Field(min_length=1)
    transition_ids: list[str] = Field(min_length=1)

    @field_validator("transition_ids")
    @classmethod
    def validate_transition_ids(cls, value: list[str]) -> list[str]:
        if any(not transition_id.strip() for transition_id in value):
            raise ValueError("transition_ids cannot contain empty values")
        return value


class BddGenerationInput(BaseModel):
    session_id: str = Field(min_length=1)
    flows: list[BddFlowInput] = Field(min_length=1)


class ResolvedState(BaseModel):
    db_id: str
    state_hash: str
    name: str
    description: str = ""
    url: str = ""
    labeling_status: str


class ResolvedTransition(BaseModel):
    db_id: str
    transition_id: str
    name: str
    action: str = ""
    action_type: str = ""
    locator_value: str
    labeling_status: str
    from_state: ResolvedState
    to_state: ResolvedState


class ResolvedFlow(BaseModel):
    checkpoint: ResolvedState
    transitions: list[ResolvedTransition]


class StepPlan(BaseModel):
    type: StepType
    id: str
    keyword: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioPlan(BaseModel):
    name: str
    steps: list[StepPlan]


class FeaturePlan(BaseModel):
    name: str
    scenarios: list[ScenarioPlan]

