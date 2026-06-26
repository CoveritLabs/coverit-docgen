import json
from enum import Enum
from typing import Any
from dataclasses import dataclass
from pydantic import BaseModel, Field, field_validator, model_validator


class StepType(str, Enum):
    STATE = "STATE"
    TRANSITION = "TRANSITION"
    DESIGN_CLASS = "DESIGN_CLASS"
    ASSERTION = "ASSERTION"
    ACTION_HOOK = "ACTION_HOOK"


class FlowEditorStepKind(str, Enum):
    DESIGN_CLASS = "design-class"
    ASSERTION = "assertion"
    ACTION_HOOK = "action-hook"

FLOW_TO_STEP_TYPE = {
    FlowEditorStepKind.DESIGN_CLASS: StepType.DESIGN_CLASS,
    FlowEditorStepKind.ASSERTION: StepType.ASSERTION,
    FlowEditorStepKind.ACTION_HOOK: StepType.ACTION_HOOK,
}

class FlowEditorPositionEdge(str, Enum):
    BEFORE = "before"
    AFTER = "after"


class FlowEditorPosition(BaseModel):
    edge: FlowEditorPositionEdge
    transitionId: str = Field(min_length=1)


class FlowEditorElementRef(BaseModel):
    selector: str | None = None
    selectorCandidates: list[str] = Field(default_factory=list)
    tag: str | None = None
    text: str | None = None
    accessibleName: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    pageUrl: str | None = None
    stateHash: str | None = None
    box: dict[str, Any] | None = None
    viewport: dict[str, Any] | None = None


class FlowEditorDraftStep(BaseModel):
    id: str = Field(min_length=1)
    kind: FlowEditorStepKind
    position: FlowEditorPosition
    order: int = 0
    label: str = ""
    element: FlowEditorElementRef | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None
    updatedAt: str | None = None


class BddFlowInput(BaseModel):
    flow_id: str | None = None
    checkpoint_hash: str = Field(min_length=1)
    transition_ids: list[str] = Field(min_length=1)
    editor_steps: list[FlowEditorDraftStep] = Field(default_factory=list)

    @field_validator("transition_ids")
    @classmethod
    def validate_transition_ids(cls, value: list[str]) -> list[str]:
        if any(not transition_id.strip() for transition_id in value):
            raise ValueError("transition_ids cannot contain empty values")
        return value

    @model_validator(mode="after")
    def validate_editor_step_positions(self) -> "BddFlowInput":
        transition_ids = set(self.transition_ids)
        unknown = sorted(
            {
                step.position.transitionId
                for step in self.editor_steps
                if step.position.transitionId not in transition_ids
            }
        )
        if unknown:
            raise ValueError(
                "editor_steps reference transition ids outside transition_ids: "
                + ", ".join(unknown)
            )
        return self


class BddGenerationInput(BaseModel):
    graph_id: str = Field(min_length=1)
    flows: list[BddFlowInput] = Field(min_length=1)
    flow_ids: list[str] = Field(default_factory=list)
    regression_codebase_id: str | None = None
    codegen_config: dict[str, Any] | None = None


class BddTransitionAction(BaseModel):
    selector: str = Field(min_length=1)
    action_type: str = ""
    value: str | None = None

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("selector cannot be empty")
        return value

    @field_validator("action_type")
    @classmethod
    def normalize_action_type(cls, value: str) -> str:
        action_type = str(value or "").strip().lower()
        if action_type == "type":
            return "fill"
        return action_type


def parse_bdd_action_values(
    raw_action_value: Any,
    fallback_selector: str,
    fallback_action_type: str,
) -> list[BddTransitionAction]:
    """Normalize crawler action metadata into executable BDD actions."""

    if isinstance(raw_action_value, str):
        raw_action_value = json.loads(raw_action_value) if raw_action_value.strip() else []

    if raw_action_value is None:
        raw_action_value = []

    if not isinstance(raw_action_value, list):
        raise ValueError("action_value must be a list")

    actions: list[BddTransitionAction] = []
    for item in raw_action_value:
        if not isinstance(item, dict):
            raise ValueError("action_value entries must be objects")

        raw_action_type = _first_string(item, "t", "action_type", "type")
        raw_value = (
            item.get("v")
            if item.get("v") is not None
            else item.get("value")
            if item.get("value") is not None
            else item.get("url")
        )
        selector = _first_string(item, "s", "selector", "locator", "locatorKey")
        if not selector and raw_action_type.lower() == "navigate" and raw_value:
            selector = str(raw_value).strip()
        if not selector:
            continue

        actions.append(
            BddTransitionAction(
                selector=selector,
                action_type=raw_action_type,
                value=None if raw_value is None else str(raw_value),
            )
        )

    if actions:
        return actions

    fallback_selector = str(fallback_selector or "").strip()
    if fallback_selector:
        return [
            BddTransitionAction(
                selector=fallback_selector,
                action_type=fallback_action_type or "",
            )
        ]

    return []


def _first_string(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
    actions: list[BddTransitionAction] = Field(default_factory=list)
    labeling_status: str
    from_state: ResolvedState
    to_state: ResolvedState


class ResolvedFlow(BaseModel):
    flow_id: str | None = None
    checkpoint: ResolvedState
    transitions: list[ResolvedTransition]
    editor_steps: list[FlowEditorDraftStep] = Field(default_factory=list)


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
    action_hooks: dict[str, dict]
    design_classes: dict[str, dict] | None = None
