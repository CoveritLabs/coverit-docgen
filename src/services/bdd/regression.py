from collections import Counter, defaultdict
from urllib.parse import urlparse
from src.utils.helpers import words, title, upper_snake, pascal, slug, url_area, jaccard
from src.models.bdd import (
    CompiledFeature,
    CompiledBdd,
    FeaturePlan,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    ScenarioPlan,
    SemanticAssertion,
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
        grouped[f"{prefix}_{upper_snake(entity.name, 'UNNAMED')}"].append(entity)

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
    return f"{pascal(stem)}{suffix}"


def _flow_labels(flow: ResolvedFlow) -> list[str]:
    labels = [flow.checkpoint.name]
    labels.extend(transition.name for transition in flow.transitions)
    labels.append(flow.transitions[-1].to_state.name)
    return labels


def _flow_urls(flow: ResolvedFlow) -> list[str]:
    urls = [flow.checkpoint.url]
    for transition in flow.transitions:
        urls.extend([transition.from_state.url, transition.to_state.url])
    return urls


def infer_feature_name(flows: list[ResolvedFlow]) -> str:
    label_tokens: list[set[str]] = []
    for flow in flows:
        for label in _flow_labels(flow):
            tokens = {
                token.lower()
                for token in words(label)
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
            return f"{title(application)} User Flows"

    return "Application User Flows"


def _base_scenario_name(flow: ResolvedFlow) -> str:
    labels = [
        title(transition.name) for transition in flow.transitions if transition.name
    ]
    if len(labels) == 1:
        return labels[0]
    if 2 <= len(labels) <= 3:
        return " Then ".join(labels)
    return (
        f"Navigate from {title(flow.checkpoint.name)} to "
        f"{title(flow.transitions[-1].to_state.name)}"
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


def scenario_names_for_flows(flows: list[ResolvedFlow]) -> list[str]:
    return _scenario_names(flows)


def _scenario_profile(flow: ResolvedFlow, scenario_name: str) -> set[str]:
    tokens: set[str] = set()
    labels = _flow_labels(flow)
    labels.append(scenario_name)
    labels.extend(transition.action for transition in flow.transitions)
    for label in labels:
        tokens.update(token.lower() for token in words(label))
    for url in _flow_urls(flow):
        parsed = urlparse(url)
        if parsed.hostname:
            tokens.update(words(parsed.hostname.split(".")[0].lower()))
        tokens.update(token.lower() for token in words(parsed.path))
    return {token for token in tokens if token not in GENERIC_FEATURE_WORDS}


def _destination_anchor(flow: ResolvedFlow) -> str:
    end_state = flow.transitions[-1].to_state
    area = url_area(end_state.url)
    if area:
        return f"url:{area}"
    return f"state:{upper_snake(end_state.name, 'UNKNOWN')}"


def _group_centroid(group: list[int], profiles: list[set[str]]) -> set[str]:
    centroid: set[str] = set()
    for index in group:
        centroid.update(profiles[index])
    return centroid


def _merge_groups(
    groups: list[list[int]],
    profiles: list[set[str]],
    threshold: float,
) -> list[list[int]]:
    merged = [list(group) for group in groups]
    changed = True
    while changed:
        changed = False
        best_pair: tuple[int, int] | None = None
        best_score = threshold
        for left_index in range(len(merged)):
            left_profile = _group_centroid(merged[left_index], profiles)
            for right_index in range(left_index + 1, len(merged)):
                score = jaccard(
                    left_profile,
                    _group_centroid(merged[right_index], profiles),
                )
                if score >= best_score:
                    best_score = score
                    best_pair = (left_index, right_index)

        if best_pair is None:
            continue

        left_index, right_index = best_pair
        merged[left_index].extend(merged[right_index])
        merged[left_index].sort()
        del merged[right_index]
        changed = True

    return merged


def _merge_singletons(
    groups: list[list[int]],
    profiles: list[set[str]],
    threshold: float,
) -> list[list[int]]:
    merged = [list(group) for group in groups]
    for group in list(merged):
        if len(group) != 1 or group not in merged:
            continue
        singleton_index = group[0]
        best_group: list[int] | None = None
        best_score = threshold
        for candidate in merged:
            if candidate == group:
                continue
            score = jaccard(
                profiles[singleton_index],
                _group_centroid(candidate, profiles),
            )
            if score >= best_score:
                best_score = score
                best_group = candidate
        if best_group is None:
            continue
        best_group.append(singleton_index)
        best_group.sort()
        merged.remove(group)
    return merged


def _feature_groups(
    flows: list[ResolvedFlow],
    split_features: bool,
    feature_similarity_threshold: float,
    singleton_merge_threshold: float,
) -> list[list[ResolvedFlow]]:
    if not split_features:
        return [flows]

    scenario_names = _scenario_names(flows)
    profiles = [
        _scenario_profile(flow, scenario_name)
        for flow, scenario_name in zip(flows, scenario_names)
    ]
    anchored: dict[str, list[int]] = defaultdict(list)
    for index, flow in enumerate(flows):
        anchored[_destination_anchor(flow)].append(index)

    groups = list(anchored.values())
    groups = _merge_groups(groups, profiles, feature_similarity_threshold)
    groups = _merge_singletons(groups, profiles, singleton_merge_threshold)
    groups.sort(key=lambda group: min(group))
    return [[flows[index] for index in group] for group in groups]


def _unique_feature_names(names: list[str]) -> list[str]:
    totals = Counter(names)
    seen: Counter[str] = Counter()
    unique: list[str] = []
    for name in names:
        if totals[name] == 1:
            unique.append(name)
            continue
        seen[name] += 1
        unique.append(f"{name} {seen[name]}")
    return unique


def _build_feature_plan(
    flows: list[ResolvedFlow],
    state_ids: dict[str, str],
    transition_ids: dict[str, str],
    flow_to_index: dict[int, int],
    semantic_assertions_by_flow_index: dict[int, list[SemanticAssertion]],
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
        for assertion in semantic_assertions_by_flow_index.get(
            flow_to_index[id(flow)],
            [],
        ):
            steps.append(
                StepPlan(
                    type=StepType.ASSERTION,
                    id=assertion.id,
                    keyword="And",
                )
            )
        scenarios.append(ScenarioPlan(name=scenario_name, steps=steps))

    return FeaturePlan(name=infer_feature_name(flows), scenarios=scenarios)


def compile_bdd(
    flows: list[ResolvedFlow],
    outgoing_locators: dict[str, list[str]],
    semantic_assertions_by_flow_index: dict[int, list[SemanticAssertion]] | None = None,
    split_features: bool = False,
    feature_similarity_threshold: float = 0.42,
    singleton_merge_threshold: float = 0.25,
) -> CompiledBdd:
    """Compile resolved graph flows into Gherkin and regression mappings."""
    if not flows:
        raise ValueError("At least one resolved flow is required")

    states, transitions = _unique_entities(flows)
    state_ids = _assign_ids(states, "S")
    transition_ids = _assign_ids(transitions, "T")
    flow_to_index = {id(flow): index for index, flow in enumerate(flows)}
    semantic_assertions_by_flow_index = semantic_assertions_by_flow_index or {}
    flow_groups = _feature_groups(
        flows,
        split_features,
        feature_similarity_threshold,
        singleton_merge_threshold,
    )
    plans = [
        _build_feature_plan(
            group,
            state_ids,
            transition_ids,
            flow_to_index,
            semantic_assertions_by_flow_index,
        )
        for group in flow_groups
    ]
    feature_names = _unique_feature_names([plan.name for plan in plans])
    features = [
        CompiledFeature(
            id=f"F_{upper_snake(feature_name, f'FEATURE_{index + 1}')}",
            feature_name=feature_name,
            feature_text=render_feature(
                FeaturePlan(
                    name=feature_name,
                    scenarios=plan.scenarios,
                )
            ),
            scenario_names=[scenario.name for scenario in plan.scenarios],
        )
        for index, (feature_name, plan) in enumerate(zip(feature_names, plans))
    ]

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
            "baselineDir": slug(state_id.removeprefix("S_")),
            "dom": {
                "elements": {locator: {"cssSelector": locator} for locator in locators}
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

    assertion_mappings = _assertion_mappings(
        semantic_assertions_by_flow_index,
        state_ids,
    )

    return CompiledBdd(
        features=features,
        states=state_mappings,
        transitions=transition_mappings,
        assertions=assertion_mappings,
        feature_name=features[0].feature_name if not split_features else None,
        feature_text=features[0].feature_text if not split_features else None,
    )


def _assertion_mappings(
    semantic_assertions_by_flow_index: dict[int, list[SemanticAssertion]],
    state_ids: dict[str, str],
) -> dict[str, dict]:
    mappings: dict[str, dict] = {}
    for assertions in semantic_assertions_by_flow_index.values():
        for assertion in assertions:
            assertion_id = assertion.id
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
                "definition": _translate_assertion_definition(
                    assertion.definition,
                    state_ids,
                ),
                "semantic": assertion.semantic,
            }
    return mappings


def _translate_assertion_definition(
    definition: dict,
    state_ids: dict[str, str],
) -> dict:
    translated = dict(definition)
    state_id = translated.get("stateId")
    if state_id in state_ids:
        translated["stateId"] = state_ids[state_id]
    return translated
