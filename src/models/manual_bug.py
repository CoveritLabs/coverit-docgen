from typing import Any

from pydantic import BaseModel, Field, field_validator


class ManualBugReportInput(BaseModel):
    report_id: str = Field(min_length=1)
    provider: str = Field(default="jira", min_length=1, max_length=50)
    session_id: str = Field(min_length=1)
    flow_id: str = Field(min_length=1)
    checkpoint_hash: str = Field(min_length=1)
    transition_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=500)
    severity: str = Field(min_length=1, max_length=50)
    current_url: str = ""
    screenshot: dict[str, Any] | None = None
    recorded_events: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("transition_ids")
    @classmethod
    def validate_transition_ids(cls, value: list[str]) -> list[str]:
        if any(not transition_id.strip() for transition_id in value):
            raise ValueError("transition_ids cannot contain empty values")
        return value
