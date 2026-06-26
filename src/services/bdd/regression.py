from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from src.models.bdd import (
    CompiledFeature,
    CompiledBdd,
    FeaturePlan,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    ScenarioPlan,
    FlowEditorDraftStep,
    SemanticAssertion,
    StepPlan,
    FLOW_TO_STEP_TYPE,
    StepType,
    FlowEditorStepKind,
    FlowEditorPositionEdge,
)
from src.utils.helpers import title, upper_snake
from src.services.bdd.gherkin import render_feature
from src.services.bdd.collect_features import collect_features, infer_feature_names
from src.services.bdd.generate_mapping import (
    generate_state_mappings,
    generate_transition_mappings,
    generate_assertion_mappings,
    generate_user_edit_mappings,
)

if TYPE_CHECKING:
    from src.services.assertions import SemanticAssertionService
from src.services.bdd.editor_steps import (
    editor_steps_by_transition,
    generated_editor_step_names,
    hook_phrase_timing,
)

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


def _build_feature_plan(
    feature_name: str,
    flows: list[ResolvedFlow],
    state_ids: dict[str, str],
    transition_ids: dict[str, str],
    flow_to_index: dict[int, int],
    semantic_assertions: dict[int, list[SemanticAssertion]],
    editor_step_names: dict[int, str],
) -> FeaturePlan:
    scenarios: list[ScenarioPlan] = []

    def make_edit_step(edit: FlowEditorDraftStep) -> StepPlan:
        metadata = {}
        if FLOW_TO_STEP_TYPE[edit.kind] == StepType.ACTION_HOOK:
            metadata["timing"] = hook_phrase_timing(edit.position.edge)
        return StepPlan(
            type=FLOW_TO_STEP_TYPE[edit.kind],
            id=editor_step_names[id(edit)],
            keyword="And",
            metadata=metadata,
        )

    for flow, scenario_name in zip(flows, _scenario_names(flows)):
        edits_by_transition = editor_steps_by_transition(flow)
        steps: list[StepPlan] = []
        steps.append(
            StepPlan(
                type=StepType.STATE,
                id=state_ids[flow.checkpoint.db_id],
                keyword="Given",
                metadata={"tense": "current"},
            )
        )

        for transition in flow.transitions:
            transition_edits = edits_by_transition.get(
                transition.transition_id,
                {
                    FlowEditorPositionEdge.BEFORE: [],
                    FlowEditorPositionEdge.AFTER: [],
                },
            )

            for edit in transition_edits[FlowEditorPositionEdge.BEFORE]:
                steps.append(make_edit_step(edit))

            steps.append(
                StepPlan(
                    type=StepType.TRANSITION,
                    id=transition_ids[transition.db_id],
                    keyword="When",
                )
            )

            for edit in transition_edits[FlowEditorPositionEdge.AFTER]:
                if edit.kind == FlowEditorStepKind.ACTION_HOOK:
                    steps.append(make_edit_step(edit))

            steps.append(
                StepPlan(
                    type=StepType.STATE,
                    id=state_ids[transition.to_state.db_id],
                    keyword="Then",
                    metadata={"tense": "expected"},
                )
            )

            for edit in transition_edits[FlowEditorPositionEdge.AFTER]:
                if edit.kind != FlowEditorStepKind.ACTION_HOOK:
                    steps.append(make_edit_step(edit))

        for assertion in semantic_assertions.get(
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
        scenarios.append(
            ScenarioPlan(
                name=scenario_name,
                steps=steps,
                flow_id=flow.flow_id,
            )
        )

    return FeaturePlan(name=feature_name, scenarios=scenarios)


async def compile_bdd(
    flows: list[ResolvedFlow],
    outgoing_locators: dict[str, list[str]],
    semantic_assertion_service: SemanticAssertionService | None = None,
) -> CompiledBdd:
    """Compile resolved graph flows into Gherkin and regression mappings."""
    if not flows:
        raise ValueError("At least one resolved flow is required")

    states, transitions = _unique_entities(flows)
    state_ids = _assign_ids(states, "S")
    transition_ids = _assign_ids(transitions, "T")
    flow_to_index = {id(flow): index for index, flow in enumerate(flows)}
    editor_step_names = generated_editor_step_names(flows)

    scenario_names = _scenario_names(flows)
    semantic_assertions = (
        await semantic_assertion_service.generate(flows, scenario_names)
        if semantic_assertion_service
        else {}
    ) or {}

    flow_groups = collect_features(flows, scenario_names=scenario_names)
    feature_names = infer_feature_names(flow_groups)

    plans = [
        _build_feature_plan(
            name,
            group,
            state_ids,
            transition_ids,
            flow_to_index,
            semantic_assertions,
            editor_step_names,
        )
        for name, group in zip(feature_names, flow_groups)
    ]

    user_assertions, action_hooks, design_classes = generate_user_edit_mappings(
        flows,
        state_ids,
        transition_ids,
        editor_step_names,
    )
    
    assertions = generate_assertion_mappings(semantic_assertions, state_ids)
    assertions.update(user_assertions)

    features = [
        CompiledFeature(
            id=f"F_{upper_snake(plan.name, f'FEATURE_{index + 1}')}",
            feature_name=plan.name,
            feature_text=render_feature(plan),
            scenario_names=[scenario.name for scenario in plan.scenarios],
        )
        for index, plan in enumerate(plans)
    ]

    return CompiledBdd(
        features=features,
        states=generate_state_mappings(
            states, state_ids, outgoing_locators, transitions
        ),
        transitions=generate_transition_mappings(
            transitions, transition_ids, state_ids
        ),
        assertions=assertions,
        action_hooks=action_hooks,
        design_classes=design_classes,
    )
