from pydantic import BaseModel, ConfigDict


class LabelStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str


class LabelTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str


class LabelGraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
