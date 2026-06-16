import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse

from src.models.bdd import (
    FeaturePlan,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    ScenarioPlan,
    StepPlan,
    StepType,
)
from src.services.bdd.gherkin import render_feature

GENERIC_FEATURE_WORDS = {
    "action",
    "click",
    "flow",
    "navigate",
    "open",
    "page",
    "screen",
    "transition",
    "user",
    "view",
}


@dataclass(frozen=True)
class CompiledBdd:
    feature_name: str
    feature_text: str
    states: dict[str, dict]
    transitions: dict[str, dict]


def _words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", value)


def _title(value: str) -> str:
    return " ".join(word.capitalize() for word in _words(value))


def _upper_snake(value: str, fallback: str) -> str:
    words = _words(value)
    return "_".join(word.upper() for word in words) or fallback


def _pascal(value: str) -> str:
    return "".join(word.capitalize() for word in _words(value))


def _slug(value: str) -> str:
    return "-".join(word.lower() for word in _words(value)) or "state"


def _unique_entities(flows: list[ResolvedFlow]):
    states: list[ResolvedState] = []
    transitions: list[ResolvedTransition] = []
    seen_states: set[str] = set()
    seen_transitions: set[str] = set()

    for flow in flows:
        flow_states = [flow.checkpoint]
        for transition in flow.transitions:
            flow_states.extend([transition.from_state, transition.to_state])
            if transition.db_id not in seen_transitions:
                seen_transitions.add(transition.db_id)
                transitions.append(transition)
        for state in flow_states:
            if state.db_id not in seen_states:
                seen_states.add(state.db_id)
                states.append(state)

    return states, transitions


def _assign_ids(entities, prefix: str) -> dict[str, str]:
    grouped: dict[str, list] = defaultdict(list)
    for entity in entities:
        grouped[f"{prefix}_{_upper_snake(entity.name, 'UNNAMED')}"].append(entity)

    assigned: dict[str, str] = {}
    for base_id, members in grouped.items():
        if len(members) == 1:
            assigned[members[0].db_id] = base_id
            continue
        for index, member in enumerate(members, start=1):
            assigned[member.db_id] = f"{base_id}_{index}"
    return assigned


def _class_name(identifier: str, prefix: str, suffix: str) -> str:
    stem = identifier.removeprefix(f"{prefix}_")
    return f"{_pascal(stem)}{suffix}"


def infer_feature_name(flows: list[ResolvedFlow]) -> str:
    label_tokens: list[set[str]] = []
    for flow in flows:
        labels = [flow.checkpoint.name]
        labels.extend(transition.name for transition in flow.transitions)
        labels.append(flow.transitions[-1].to_state.name)
        for label in labels:
            tokens = {
                token.lower()
                for token in _words(label)
                if token.lower() not in GENERIC_FEATURE_WORDS
            }
            if tokens:
                label_tokens.append(tokens)

    shared = set.intersection(*label_tokens) if label_tokens else set()
    if shared:
        ordered = sorted(shared)
        return f"{' '.join(word.capitalize() for word in ordered)} User Flows"

    hostnames = {
        urlparse(flow.checkpoint.url).hostname
        for flow in flows
        if urlparse(flow.checkpoint.url).hostname
    }
    if len(hostnames) == 1:
        hostname = next(iter(hostnames))
        application = hostname.split(".")[0].replace("-", " ")
        if application:
            return f"{_title(application)} User Flows"

    return "Application User Flows"


def _base_scenario_name(flow: ResolvedFlow) -> str:
    labels = [
        _title(transition.name)
        for transition in flow.transitions
        if transition.name
    ]
    if len(labels) == 1:
        return labels[0]
    if 2 <= len(labels) <= 3:
        return " Then ".join(labels)
    return (
        f"Navigate from {_title(flow.checkpoint.name)} to "
        f"{_title(flow.transitions[-1].to_state.name)}"
    )


def _scenario_names(flows: list[ResolvedFlow]) -> list[str]:
    base_names = [_base_scenario_name(flow) for flow in flows]
    totals = Counter(base_names)
    seen: Counter[str] = Counter()
    names: list[str] = []
    for base_name in base_names:
        if totals[base_name] == 1:
            names.append(base_name)
            continue
        seen[base_name] += 1
        names.append(f"{base_name} Scenario {seen[base_name]}")
    return names


def _build_feature_plan(
    flows: list[ResolvedFlow],
    state_ids: dict[str, str],
    transition_ids: dict[str, str],
) -> FeaturePlan:
    scenarios: list[ScenarioPlan] = []
    for flow, scenario_name in zip(flows, _scenario_names(flows)):
        steps = [
            StepPlan(
                type=StepType.STATE,
                id=state_ids[flow.checkpoint.db_id],
                keyword="Given",
                metadata={"tense": "current"},
            )
        ]
        for index, transition in enumerate(flow.transitions):
            steps.append(
                StepPlan(
                    type=StepType.TRANSITION,
                    id=transition_ids[transition.db_id],
                    keyword="When" if index == 0 else "And",
                )
            )
        steps.append(
            StepPlan(
                type=StepType.STATE,
                id=state_ids[flow.transitions[-1].to_state.db_id],
                keyword="Then",
                metadata={"tense": "expected"},
            )
        )
        scenarios.append(ScenarioPlan(name=scenario_name, steps=steps))

    return FeaturePlan(name=infer_feature_name(flows), scenarios=scenarios)


def compile_bdd(
    flows: list[ResolvedFlow],
    outgoing_locators: dict[str, list[str]],
) -> CompiledBdd:
    """Compile resolved graph flows into Gherkin and regression mappings."""
    if not flows:
        raise ValueError("At least one resolved flow is required")

    states, transitions = _unique_entities(flows)
    state_ids = _assign_ids(states, "S")
    transition_ids = _assign_ids(transitions, "T")
    plan = _build_feature_plan(flows, state_ids, transition_ids)

    state_mappings: dict[str, dict] = {}
    for state in states:
        state_id = state_ids[state.db_id]
        locators = outgoing_locators.get(state.state_hash, [])
        state_mappings[state_id] = {
            "id": state_id,
            "dbId": state.db_id,
            "type": StepType.STATE.value,
            "label": state.name,
            "description": state.description,
            "url": state.url,
            "className": _class_name(state_id, "S", "State"),
            "baselineDir": _slug(state_id.removeprefix("S_")),
            "dom": {
                "elements": {
                    locator: {"cssSelector": locator}
                    for locator in locators
                }
            },
        }

    transition_mappings: dict[str, dict] = {}
    for transition in transitions:
        transition_id = transition_ids[transition.db_id]
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
            "action": {
                "type": transition.action_type,
                "stateId": state_ids[transition.from_state.db_id],
                "locatorKey": transition.locator_value,
            },
        }

    return CompiledBdd(
        feature_name=plan.name,
        feature_text=render_feature(plan),
        states=state_mappings,
        transitions=transition_mappings,
    )
