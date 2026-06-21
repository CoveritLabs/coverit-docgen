from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class VideoGenerationResult(BaseModel):
    status: Literal["success"]
    session_id: str
    artifact_path: str
    duration_seconds: float
    resolution: str
    fps: int
    flow_count: int


class VideoActionValue(BaseModel):
    selector: str = Field(min_length=1)
    action_type: str = ""
    value: str | None = None

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("selector cannot be empty")
        return value


class VideoResolvedTransition(BaseModel):
    transition_id: str
    action_type: str = ""
    locator_value: str = ""
    action_value: list[VideoActionValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_action_target(self):
        if not self.action_value and not self.locator_value.strip():
            raise ValueError(
                f"Transition {self.transition_id} has no selector metadata"
            )
        return self


class VideoResolvedFlow(BaseModel):
    start_url: str
    transitions: list[VideoResolvedTransition]


def parse_video_action_values(
    raw_action_value: Any,
    fallback_selector: str,
    fallback_action_type: str,
) -> list[VideoActionValue]:
    """Normalize crawler action metadata into explicit video sub-actions."""

    if isinstance(raw_action_value, str):
        import json

        raw_action_value = json.loads(raw_action_value) if raw_action_value else []

    if raw_action_value is None:
        raw_action_value = []

    if not isinstance(raw_action_value, list):
        raise ValueError("action_value must be a list")

    actions: list[VideoActionValue] = []
    for item in raw_action_value:
        if not isinstance(item, dict):
            raise ValueError("action_value entries must be objects")
        selector = item.get("s") or item.get("selector") or item.get("locator")
        if not selector:
            continue
        actions.append(
            VideoActionValue(
                selector=selector,
                action_type=item.get("t") or item.get("action_type") or "",
                value=item.get("v") if item.get("v") is not None else item.get("value"),
            )
        )

    if actions:
        return actions

    if fallback_selector and fallback_selector.strip():
        return [
            VideoActionValue(
                selector=fallback_selector,
                action_type=fallback_action_type or "",
                value=None,
            )
        ]

    return []
