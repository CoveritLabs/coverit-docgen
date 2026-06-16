from collections.abc import Callable

from src.models.bdd import FeaturePlan, StepPlan, StepType

StepRenderer = Callable[[StepPlan], str]


def _render_state(step: StepPlan) -> str:
    tense = step.metadata.get("tense", "current")
    phrase = "is in" if tense == "current" else "should be in"
    return f'{step.keyword} the UI {phrase} state "{step.id}"'


def _render_transition(step: StepPlan) -> str:
    return f'{step.keyword} I perform transition "{step.id}"'


def _render_assertion(step: StepPlan) -> str:
    return f'{step.keyword} I assert "{step.id}"'


def _render_action_hook(step: StepPlan) -> str:
    timing = step.metadata.get("timing", "after")
    return f'{step.keyword} {timing} action I run hook "{step.id}"'


DEFAULT_STEP_RENDERERS: dict[StepType, StepRenderer] = {
    StepType.STATE: _render_state,
    StepType.TRANSITION: _render_transition,
    StepType.ASSERTION: _render_assertion,
    StepType.ACTION_HOOK: _render_action_hook,
}


def render_feature(
    plan: FeaturePlan,
    renderers: dict[StepType, StepRenderer] | None = None,
) -> str:
    """Render a typed feature plan using fixed, parser-compatible phrases."""
    step_renderers = {**DEFAULT_STEP_RENDERERS, **(renderers or {})}
    lines = [f"Feature: {plan.name}"]

    for scenario in plan.scenarios:
        lines.extend(["", f"  Scenario: {scenario.name}"])
        for step in scenario.steps:
            renderer = step_renderers.get(step.type)
            if renderer is None:
                raise ValueError(f"No renderer registered for {step.type}")
            lines.append(f"    {renderer(step)}")

    return "\n".join(lines) + "\n"
