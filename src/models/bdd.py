from enum import Enum
from typing import Any
from dataclasses import dataclass
from pydantic import BaseModel, Field, field_validator


class StepType(str, Enum):
    STATE = "STATE"
    TRANSITION = "TRANSITION"
    ASSERTION = "ASSERTION"
    ACTION_HOOK = "ACTION_HOOK"


class BddFlowInput(BaseModel):
    flow_id: str | None = None
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
    graph_id: str | None = None
    flows: list[BddFlowInput] = Field(min_length=1)
    flow_ids: list[str] = Field(default_factory=list)
    regression_codebase_id: str | None = None
    codegen_config: dict[str, Any] | None = None


class ResolvedState(BaseModel):
    db_id: str
    state_hash: str
    name: str
    description: str = ""
    url: str = ""
    html: str = ""
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
    flow_id: str | None = None
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
    flow_id: str | None = None


class FeaturePlan(BaseModel):
    name: str
    scenarios: list[ScenarioPlan]


class SemanticAssertion(BaseModel):
    id: str
    db_id: str
    label: str
    description: str = ""
    target_state_db_id: str
    context_id: str
    severity: str = "blocking"
    definition: dict[str, Any]
    semantic: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class CompiledFeature:
    id: str
    feature_name: str
    feature_text: str
    scenario_names: list[str]


@dataclass(frozen=True)
class CompiledBdd:
    features: list[CompiledFeature]
    states: dict[str, dict]
    transitions: dict[str, dict]
    assertions: dict[str, dict]
    feature_name: str | None = None
    feature_text: str | None = None
