from collections import defaultdict
from typing import Literal

from src.models.bdd import (
    FLOW_TO_STEP_TYPE,
    FlowEditorDraftStep,
    FlowEditorPositionEdge,
    FlowEditorStepKind,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    StepType,
)

DESIGN_CLASS_ID = "scenarioData"
HookPhraseTiming = Literal["before", "after"]
HookMappingTiming = Literal["pre", "post"]


def editor_step_sort_key(step: FlowEditorDraftStep) -> tuple[str, int, int, str]:
    edge_rank = 0 if step.position.edge == FlowEditorPositionEdge.BEFORE else 1
    return (step.position.transitionId, edge_rank, step.order, step.id)


def sorted_editor_steps(
    steps: list[FlowEditorDraftStep],
) -> list[FlowEditorDraftStep]:
    return sorted(steps, key=editor_step_sort_key)


def transition_by_input_id(flow: ResolvedFlow) -> dict[str, ResolvedTransition]:
    return {transition.transition_id: transition for transition in flow.transitions}


def editor_steps_by_transition(
    flow: ResolvedFlow,
) -> dict[str, dict[FlowEditorPositionEdge, list[FlowEditorDraftStep]]]:
    grouped: dict[str, dict[FlowEditorPositionEdge, list[FlowEditorDraftStep]]] = (
        defaultdict(lambda: {FlowEditorPositionEdge.BEFORE: [], FlowEditorPositionEdge.AFTER: []})
    )
    for step in sorted_editor_steps(flow.editor_steps):
        grouped[step.position.transitionId][step.position.edge].append(step)
    return grouped


def hook_phrase_timing(edge: FlowEditorPositionEdge) -> HookPhraseTiming:
    return "before" if edge == FlowEditorPositionEdge.BEFORE else "after"


def hook_mapping_timing(edge: FlowEditorPositionEdge) -> HookMappingTiming:
    return "pre" if edge == FlowEditorPositionEdge.BEFORE else "post"


def target_state_for_editor_step(
    step: FlowEditorDraftStep,
    transition: ResolvedTransition,
) -> ResolvedState:
    if step.position.edge == FlowEditorPositionEdge.BEFORE:
        return transition.from_state
    return transition.to_state


def executable_step_type(step: FlowEditorDraftStep) -> StepType:
    if step.kind == FlowEditorStepKind.DESIGN_CLASS:
        return StepType.ACTION_HOOK
    return FLOW_TO_STEP_TYPE[step.kind]
