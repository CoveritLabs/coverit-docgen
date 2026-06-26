from typing import Any

from src.utils.helpers import slug, pascal
from collections import defaultdict
from src.models.bdd import (
    BddTransitionAction,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    SemanticAssertion,
    FlowEditorStepKind,
    StepType,
)
from src.services.bdd.editor_steps import (
    target_state_for_editor_step,
    transition_by_input_id,
)

def _class_name(identifier: str, prefix: str, suffix: str) -> str:
    stem = identifier.removeprefix(f"{prefix}_")
    return f"{pascal(stem)}{suffix}"


def _unique_locators(*groups: list[str]) -> list[str]:
    locators: list[str] = []
    for group in groups:
        for locator in group:
            locator = str(locator or "").strip()
            if locator and locator not in locators:
                locators.append(locator)
    return locators


def _effective_transition_actions(
    transition: ResolvedTransition,
) -> list[BddTransitionAction]:
    if transition.actions:
        return transition.actions
    if transition.locator_value.strip():
        return [
            BddTransitionAction(
                selector=transition.locator_value,
                action_type=transition.action_type,
            )
        ]
    return []


def _transition_action_mapping(
    action: BddTransitionAction,
    state_id: str,
) -> dict[str, str]:
    mapping = {
        "type": action.action_type,
        "stateId": state_id,
    }
    if action.action_type == "navigate":
        mapping["url"] = action.value or action.selector
        return mapping

    mapping["locatorKey"] = action.selector
    if action.action_type in {"fill", "select"} and action.value is not None:
        mapping["value"] = action.value
    return mapping


def _action_locators_by_state_hash(
    transitions: list[ResolvedTransition],
) -> dict[str, list[str]]:
    locators: dict[str, list[str]] = defaultdict(list)
    for transition in transitions:
        for action in _effective_transition_actions(transition):
            if action.action_type == "navigate":
                continue
            state_hash = transition.from_state.state_hash
            if action.selector not in locators[state_hash]:
                locators[state_hash].append(action.selector)
    return locators


def generate_state_mappings(
    states: list[ResolvedState],
    state_ids: dict[str, str],
    outgoing_locators: dict[str, list[str]],
    transitions: list[ResolvedTransition],
) -> dict[str, dict]:
    state_mappings: dict[str, dict] = {}
    action_locators = _action_locators_by_state_hash(transitions)
    for state in states:
        state_id = state_ids[state.db_id]
        locators = _unique_locators(
            outgoing_locators.get(state.state_hash, []),
            action_locators.get(state.state_hash, []),
        )
        state_mappings[state_id] = {
            "id": state_id,
            "dbId": state.db_id,
            "type": StepType.STATE.value,
            "label": state.name,
            "description": state.description,
            "url": state.url,
            "className": _class_name(state_id, "S", "State"),
            "baselineDir": slug(state_id.removeprefix("S_")),
            "dom": {
                "elements": {locator: {"cssSelector": locator} for locator in locators}
            },
        }
    return state_mappings


def generate_transition_mappings(
    transitions: list[ResolvedTransition],
    transition_ids: dict[str, str],
    state_ids: dict[str, str],
) -> dict[str, dict]:
    transition_mappings: dict[str, dict] = {}
    for transition in transitions:
        transition_id = transition_ids[transition.db_id]
        source_state_id = state_ids[transition.from_state.db_id]
        transition_mappings[transition_id] = {
            "id": transition_id,
            "dbId": transition.db_id,
            "type": StepType.TRANSITION.value,
            "label": transition.name,
            "description": transition.action,
            "className": _class_name(
                transition_id,
                "T",
                "Transition",
            ),
            "actions": [
                _transition_action_mapping(action, source_state_id)
                for action in _effective_transition_actions(transition)
            ],
        }
    return transition_mappings


def generate_assertion_mappings(
    semantic_assertions_by_flow_index: dict[int, list[SemanticAssertion]],
    state_ids: dict[str, str],
) -> dict[str, dict]:
    mappings: dict[str, dict] = {}
    for assertions in semantic_assertions_by_flow_index.values():
        for assertion in assertions:
            assertion_id = assertion.id

            definition = dict(assertion.definition)
            if definition.get("stateId") in state_ids:
                definition["stateId"] = state_ids[definition.get("stateId")]

            mappings[assertion_id] = {
                "id": assertion_id,
                "dbId": assertion.db_id,
                "type": StepType.ASSERTION.value,
                "label": assertion.label,
                "description": assertion.description,
                "targetId": state_ids.get(
                    assertion.target_state_db_id,
                    assertion.target_state_db_id,
                ),
                "contextId": assertion.context_id,
                "severity": assertion.severity,
                "definition": definition,
                "semantic": assertion.semantic,
            }
    return mappings


def generate_user_edit_mappings(
    flows: list[ResolvedFlow],
    state_ids: dict[str, str],
    transition_ids: dict[str, str],
    editor_step_names: dict[int, str],
) -> tuple[dict[str, dict], dict[str, dict], dict[str, Any]]:
    assertions: dict[str, dict] = {}
    action_hooks: dict[str, dict] = {}
    design_classes: dict[str, dict] = {}

    for flow in flows:
        transitions_by_input_id = transition_by_input_id(flow)
        for step in flow.editor_steps:
            transition = transitions_by_input_id.get(step.position.transitionId)
            if transition is None:
                raise ValueError(
                    f"Editor step {step.id} references unknown transition "
                    f"{step.position.transitionId}"
                )

            transition_id = transition_ids[transition.db_id]
            state_id = state_ids[target_state_for_editor_step(step, transition).db_id]
            step_name = editor_step_names[id(step)]
            if step.kind == FlowEditorStepKind.ASSERTION:
                assertions[step_name] = {
                    **step.model_dump(),
                    "type": StepType.ASSERTION.value,
                    "stateId": state_id,
                    "transitionId": transition_id,
                }
                continue

            if step.kind == FlowEditorStepKind.ACTION_HOOK:
                action_hooks[step_name] = {
                    **step.model_dump(),
                    "type": StepType.ACTION_HOOK.value,
                    "transitionId": transition_id,
                }
                continue

            if step.kind == FlowEditorStepKind.DESIGN_CLASS:
                design_classes[step_name] = {
                    **step.model_dump(),
                    "type": StepType.DESIGN_CLASS.value,
                    "stateId": state_id,
                    "transitionId": transition_id,
                }
                continue

    return assertions, action_hooks, design_classes
