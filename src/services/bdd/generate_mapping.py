from copy import deepcopy
import re
from typing import Any

from src.utils.helpers import slug, pascal
from collections import defaultdict
from src.models.bdd import (
    BddTransitionAction,
    FlowEditorDraftStep,
    FlowEditorStepKind,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    SemanticAssertion,
    StepType,
)
from src.services.bdd.editor_steps import (
    DESIGN_CLASS_ID,
    hook_mapping_timing,
    sorted_editor_steps,
    target_state_for_editor_step,
    transition_by_input_id,
)

ELEMENT_EXTRACT_SOURCES = {
    "text",
    "innerText",
    "html",
    "value",
    "checked",
    "visible",
    "count",
    "list",
}


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
) -> tuple[dict[str, dict], dict[str, dict], dict[str, Any]]:
    assertions: dict[str, dict] = {}
    action_hooks: dict[str, dict] = {}
    design_class = default_design_class_mapping()

    for flow in flows:
        transitions_by_input_id = transition_by_input_id(flow)
        for step in sorted_editor_steps(flow.editor_steps):
            transition = transitions_by_input_id.get(step.position.transitionId)
            if transition is None:
                raise ValueError(
                    f"Editor step {step.id} references unknown transition "
                    f"{step.position.transitionId}"
                )

            transition_id = transition_ids[transition.db_id]
            state_id = state_ids[target_state_for_editor_step(step, transition).db_id]

            if step.kind == FlowEditorStepKind.ASSERTION:
                _add_user_assertion_mapping(
                    assertions,
                    design_class,
                    step,
                    transition_id,
                    state_id,
                    state_ids,
                )
                continue

            if step.kind == FlowEditorStepKind.ACTION_HOOK:
                _add_action_hook_mapping(
                    action_hooks,
                    step,
                    transition_id,
                    state_id,
                    _normalise_definition(step.definition, state_id, state_ids),
                )
                continue

            if step.kind == FlowEditorStepKind.DESIGN_CLASS:
                operation = _design_operation_from_step(step, state_id, design_class)
                _ensure_unique(design_class["operations"], step.id, "design operation")
                design_class["operations"][step.id] = operation
                _add_action_hook_mapping(
                    action_hooks,
                    step,
                    transition_id,
                    state_id,
                    {"type": "design-operation", "operationId": step.id},
                )

    return assertions, action_hooks, design_class


def default_design_class_mapping() -> dict[str, Any]:
    return {
        "id": DESIGN_CLASS_ID,
        "label": "Scenario Data",
        "description": "Single scenario data store for generated regression flows.",
        "store": {},
        "extracts": {},
        "expressions": {},
        "functions": {},
        "assertionFunctions": {},
        "operations": {},
        "overwritable": True,
    }


def _add_user_assertion_mapping(
    assertions: dict[str, dict],
    design_class: dict[str, Any],
    step: FlowEditorDraftStep,
    transition_id: str,
    state_id: str,
    state_ids: dict[str, str],
) -> None:
    _ensure_unique(assertions, step.id, "assertion")
    definition = deepcopy(step.definition or {})

    if definition.get("type") == "function":
        function_id = _function_id(definition, step)
        assertion_function = {
            "description": step.label or f"User assertion {step.id}",
        }
        if definition.get("code"):
            assertion_function["code"] = deepcopy(definition["code"])
        if definition.get("severity"):
            assertion_function["severity"] = definition["severity"]
        _put_unique(
            design_class["assertionFunctions"],
            function_id,
            assertion_function,
            "assertion function",
        )

        mapped_definition = {
            "type": "user-assertion",
            "functionId": function_id,
        }
        if definition.get("args") is not None:
            mapped_definition["args"] = deepcopy(definition["args"])
    else:
        mapped_definition = _normalise_definition(definition, state_id, state_ids)

    assertions[step.id] = {
        "id": step.id,
        "type": StepType.ASSERTION.value,
        "label": step.label or f"User assertion {step.id}",
        "description": step.label or "",
        "targetId": state_id,
        "contextId": transition_id,
        "severity": definition.get("severity", "blocking"),
        "definition": mapped_definition,
        "editorStep": _editor_step_metadata(step),
    }


def _add_action_hook_mapping(
    action_hooks: dict[str, dict],
    step: FlowEditorDraftStep,
    transition_id: str,
    state_id: str,
    definition: dict[str, Any],
) -> None:
    _ensure_unique(action_hooks, step.id, "action hook")
    action_hooks[step.id] = {
        "id": step.id,
        "type": StepType.ACTION_HOOK.value,
        "label": step.label or f"User edit {step.id}",
        "description": step.label or "",
        "timing": hook_mapping_timing(step.position.edge),
        "targetType": "transition",
        "targetId": transition_id,
        "contextId": transition_id,
        "order": step.order,
        "enabled": True,
        "definition": definition,
        "editorStep": _editor_step_metadata(step),
    }


def _design_operation_from_step(
    step: FlowEditorDraftStep,
    state_id: str,
    design_class: dict[str, Any],
) -> dict[str, Any]:
    definition = deepcopy(step.definition or {})

    if definition.get("type") == "function":
        function_id = _function_id(definition, step)
        design_function = {
            "description": step.label or f"User design function {function_id}",
        }
        if definition.get("code"):
            design_function["code"] = deepcopy(definition["code"])
        _put_unique(
            design_class["functions"],
            function_id,
            design_function,
            "design function",
        )

        operation: dict[str, Any] = {
            "type": "call-function",
            "functionId": function_id,
        }
        if definition.get("args") is not None:
            operation["args"] = _normalise_design_values(
                definition["args"],
                step,
                state_id,
                design_class,
                "args",
            )
        if definition.get("assignTo"):
            operation["assignTo"] = definition["assignTo"]
            _ensure_store_slot(design_class, definition["assignTo"], step.label)
        if step.label:
            operation["description"] = step.label
        return operation

    operation = _normalise_design_values(
        definition,
        step,
        state_id,
        design_class,
        "operation",
    )
    if step.label and isinstance(operation, dict):
        operation.setdefault("description", step.label)
    if isinstance(operation, dict):
        key = operation.get("key")
        if isinstance(key, str) and key:
            _ensure_store_slot(design_class, key, step.label)
    return (
        operation
        if isinstance(operation, dict)
        else {"type": "set", "value": operation}
    )


def _normalise_definition(
    definition: dict[str, Any],
    state_id: str,
    state_ids: dict[str, str],
) -> dict[str, Any]:
    normalised = _replace_state_refs(deepcopy(definition or {}), state_ids)
    _inject_state_id(normalised, state_id)
    return normalised


def _replace_state_refs(value: Any, state_ids: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [_replace_state_refs(item, state_ids) for item in value]
    if not isinstance(value, dict):
        return value
    replaced: dict[str, Any] = {}
    for key, item in value.items():
        if key == "stateId" and isinstance(item, str):
            replaced[key] = state_ids.get(item, item)
        else:
            replaced[key] = _replace_state_refs(item, state_ids)
    return replaced


def _inject_state_id(value: Any, state_id: str) -> None:
    if isinstance(value, list):
        for item in value:
            _inject_state_id(item, state_id)
        return
    if not isinstance(value, dict):
        return

    if value.get("type") in {"element", "element-interaction"} and not value.get(
        "stateId"
    ):
        value["stateId"] = state_id

    for item in value.values():
        _inject_state_id(item, state_id)


def _normalise_design_values(
    value: Any,
    step: FlowEditorDraftStep,
    state_id: str,
    design_class: dict[str, Any],
    path: str,
) -> Any:
    if isinstance(value, list):
        return [
            _normalise_design_values(
                item, step, state_id, design_class, f"{path}_{index}"
            )
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        return value

    if value.get("source") == "element":
        return _element_value_as_extract(value, step, state_id, design_class, path)

    return {
        key: _normalise_design_values(
            item,
            step,
            state_id,
            design_class,
            f"{path}_{key}",
        )
        for key, item in value.items()
    }


def _element_value_as_extract(
    value: dict[str, Any],
    step: FlowEditorDraftStep,
    state_id: str,
    design_class: dict[str, Any],
    path: str,
) -> dict[str, str]:
    selector = _first_text(
        value.get("selector"),
        value.get("locatorKey"),
        value.get("cssSelector"),
        step.element.selector if step.element else None,
    )
    if not selector:
        raise ValueError(
            f"Design class editor step {step.id} is missing an element selector"
        )

    extract_id = _safe_identifier(f"{step.id}_{path}")
    source_hint = _first_text(value.get("attribute"), value.get("token"), "text")
    extract: dict[str, Any] = {
        "stateId": state_id,
        "locator": {"cssSelector": selector},
        "source": (
            source_hint if source_hint in ELEMENT_EXTRACT_SOURCES else "attribute"
        ),
        "description": step.label or f"Extract for {step.id}",
    }
    if extract["source"] == "attribute":
        extract["attributeName"] = source_hint

    _put_unique(design_class["extracts"], extract_id, extract, "design extract")
    return {"from": extract_id}


def _function_id(definition: dict[str, Any], step: FlowEditorDraftStep) -> str:
    return _first_text(definition.get("functionId"), step.id) or step.id


def _ensure_store_slot(
    design_class: dict[str, Any],
    key: str,
    label: str,
) -> None:
    design_class["store"].setdefault(
        key,
        {
            "reset": "scenario",
            "description": label or f"User-edited value {key}",
        },
    )


def _editor_step_metadata(step: FlowEditorDraftStep) -> dict[str, Any]:
    return step.model_dump(mode="json", exclude_none=True)


def _ensure_unique(mapping: dict[str, Any], key: str, label: str) -> None:
    if key in mapping:
        raise ValueError(f"Duplicate {label} id from editor steps: {key}")


def _put_unique(
    mapping: dict[str, Any],
    key: str,
    value: dict[str, Any],
    label: str,
) -> None:
    existing = mapping.get(key)
    if existing is not None and existing != value:
        raise ValueError(f"Conflicting {label} definition for id: {key}")
    mapping[key] = value


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return safe or "editor_value"
