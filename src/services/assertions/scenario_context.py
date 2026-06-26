from dataclasses import dataclass

from src.models.bdd import ResolvedFlow, ResolvedState
from src.services.assertions.html_summarizer import HtmlSummary, summarize_html


@dataclass(frozen=True)
class TransitionContext:
    db_id: str
    transition_id: str
    name: str
    action: str
    action_type: str
    locator_value: str
    from_state_db_id: str
    to_state_db_id: str


@dataclass(frozen=True)
class StateContext:
    db_id: str
    name: str
    description: str
    url: str
    summary: HtmlSummary


@dataclass(frozen=True)
class ScenarioContext:
    index: int
    name: str
    checkpoint: StateContext
    final_state: StateContext
    states: list[StateContext]
    transitions: list[TransitionContext]

    def model_payload(self) -> dict:
        return {
            "scenarioIndex": self.index,
            "scenarioName": self.name,
            "scope": "scenario",
            "checkpoint": self._state_payload(self.checkpoint),
            "finalState": self._state_payload(self.final_state),
            "states": [self._state_payload(state) for state in self.states],
            "transitions": [
                {
                    "dbId": transition.db_id,
                    "transitionId": transition.transition_id,
                    "name": transition.name,
                    "action": transition.action,
                    "actionType": transition.action_type,
                    "locatorValue": transition.locator_value,
                    "fromStateDbId": transition.from_state_db_id,
                    "toStateDbId": transition.to_state_db_id,
                }
                for transition in self.transitions
            ],
        }

    @staticmethod
    def _state_payload(state: StateContext) -> dict:
        return {
            "dbId": state.db_id,
            "name": state.name,
            "description": state.description,
            "url": state.url,
            "dom": state.summary.model_payload(),
        }


def build_scenario_contexts(
    flows: list[ResolvedFlow],
    scenario_names: list[str],
    html_summary_max_chars: int,
) -> list[ScenarioContext]:
    contexts: list[ScenarioContext] = []
    for index, (flow, scenario_name) in enumerate(zip(flows, scenario_names)):
        state_by_id = {flow.checkpoint.db_id: _state_context(flow.checkpoint, html_summary_max_chars)}
        transitions: list[TransitionContext] = []
        for transition in flow.transitions:
            state_by_id.setdefault(
                transition.from_state.db_id,
                _state_context(transition.from_state, html_summary_max_chars),
            )
            state_by_id.setdefault(
                transition.to_state.db_id,
                _state_context(transition.to_state, html_summary_max_chars),
            )
            transitions.append(
                TransitionContext(
                    db_id=transition.db_id,
                    transition_id=transition.transition_id,
                    name=transition.name,
                    action=transition.action,
                    action_type=transition.action_type,
                    locator_value=transition.locator_value,
                    from_state_db_id=transition.from_state.db_id,
                    to_state_db_id=transition.to_state.db_id,
                )
            )

        contexts.append(
            ScenarioContext(
                index=index,
                name=scenario_name,
                checkpoint=state_by_id[flow.checkpoint.db_id],
                final_state=state_by_id[flow.transitions[-1].to_state.db_id],
                states=list(state_by_id.values()),
                transitions=transitions,
            )
        )
    return contexts


def _state_context(state: ResolvedState, html_summary_max_chars: int) -> StateContext:
    return StateContext(
        db_id=state.db_id,
        name=state.name,
        description=state.description,
        url=state.url,
        summary=summarize_html(state.html, html_summary_max_chars),
    )
