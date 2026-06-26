from collections import defaultdict
from typing import Literal

from src.models.bdd import (
    FlowEditorDraftStep,
    FlowEditorPositionEdge,
    FlowEditorStepKind,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
)

HookPhraseTiming = Literal["before", "after"]
HookMappingTiming = Literal["pre", "post"]

EDITOR_STEP_NAME_PREFIXES = {
    FlowEditorStepKind.ASSERTION: "ASSERTION",
    FlowEditorStepKind.ACTION_HOOK: "HOOK",
    FlowEditorStepKind.DESIGN_CLASS: "DESIGN_CLASS",
}


def transition_by_input_id(flow: ResolvedFlow) -> dict[str, ResolvedTransition]:
    return {transition.transition_id: transition for transition in flow.transitions}


def editor_steps_by_transition(
    flow: ResolvedFlow,
) -> dict[str, dict[FlowEditorPositionEdge, list[FlowEditorDraftStep]]]:
    grouped: dict[str, dict[FlowEditorPositionEdge, list[FlowEditorDraftStep]]] = (
        defaultdict(
            lambda: {
                FlowEditorPositionEdge.BEFORE: [],
                FlowEditorPositionEdge.AFTER: [],
            }
        )
    )
    for step in flow.editor_steps:
        grouped[step.position.transitionId][step.position.edge].append(step)
    return grouped


def generated_editor_step_names(flows: list[ResolvedFlow]) -> dict[int, str]:
    counters: dict[FlowEditorStepKind, int] = defaultdict(int)
    names: dict[int, str] = {}
    for flow in flows:
        for step in flow.editor_steps:
            counters[step.kind] += 1
            names[id(step)] = (
                f"{EDITOR_STEP_NAME_PREFIXES[step.kind]}_{counters[step.kind]}"
            )
    return names


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
