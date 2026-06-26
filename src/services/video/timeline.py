from dataclasses import dataclass

from src.models.video import VideoActionValue, VideoResolvedFlow


TEXT_ACTION_TYPES = {
    "fill",
    "type",
    "input",
    "text",
    "textarea",
    "keyboard",
}


@dataclass(frozen=True)
class VideoShot:
    transition_id: str
    selector: str
    action_type: str
    value: str | None

    @property
    def has_typing(self) -> bool:
        if self.value is None or self.value == "":
            return False
        normalized = self.action_type.lower()
        return not normalized or normalized in TEXT_ACTION_TYPES


@dataclass(frozen=True)
class VideoFlowTimeline:
    start_url: str
    shots: list[VideoShot]


def build_timelines(flows: list[VideoResolvedFlow]) -> list[VideoFlowTimeline]:
    timelines: list[VideoFlowTimeline] = []
    for flow in flows:
        shots: list[VideoShot] = []
        for transition in flow.transitions:
            actions = transition.action_value or [
                VideoActionValue(
                    selector=transition.locator_value,
                    action_type=transition.action_type,
                )
            ]
            for action in actions:
                shots.append(
                    VideoShot(
                        transition_id=transition.transition_id,
                        selector=action.selector,
                        action_type=action.action_type or transition.action_type,
                        value=action.value,
                    )
                )
        timelines.append(VideoFlowTimeline(start_url=flow.start_url, shots=shots))
    return timelines