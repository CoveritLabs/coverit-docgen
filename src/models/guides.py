from typing import Literal

from pydantic import BaseModel, Field


class UserGuideInput(BaseModel):
    session_id: str = Field(min_length=1)
    start_state_hash: str = Field(min_length=1)
    end_state_hash: str = Field(min_length=1)


class ResolvedGuideState(BaseModel):
    db_id: str
    state_hash: str
    name: str
    description: str = ""
    url: str = ""
    labeling_status: str = ""


class ResolvedGuideTransition(BaseModel):
    db_id: str
    transition_id: str
    name: str = ""
    action: str
    action_type: str = ""
    locator_value: str = ""
    labeling_status: str = ""
    from_state: ResolvedGuideState
    to_state: ResolvedGuideState


class ResolvedGuidePath(BaseModel):
    start_state: ResolvedGuideState
    end_state: ResolvedGuideState
    transitions: list[ResolvedGuideTransition] = Field(default_factory=list)


class UserGuideResult(BaseModel):
    status: Literal["success"]
    session_id: str
    start_state_hash: str
    end_state_hash: str
    guide: str
    step_count: int
