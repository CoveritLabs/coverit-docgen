import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.models.bdd import SemanticAssertion
from src.services.assertions.scenario_context import ScenarioContext
from src.utils.helpers import upper_snake

VOLATILE_TEXT = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
    r"|([0-9a-f]{16,})"
    r"|(\d{4}-\d{2}-\d{2})"
    r"|(\d{1,2}:\d{2})",
    re.IGNORECASE,
)


class ModelAssertionProposal(BaseModel):
    purpose: str = Field(min_length=1)
    targetStateDbId: str = Field(min_length=1)
    contextTransitionDbId: str | None = None
    label: str = Field(min_length=1)
    description: str = ""
    severity: Literal["blocking", "warning", "info"] = "blocking"
    definition: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    reason: str = ""

    @field_validator("label", "purpose", "description", "reason")
    @classmethod
    def reject_volatile_text(cls, value: str) -> str:
        if VOLATILE_TEXT.search(value or ""):
            raise ValueError("volatile value is not allowed in semantic assertion text")
        return value

    @field_validator("definition")
    @classmethod
    def reject_incomplete_definition(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("definition must not be empty")
        definition_type = value.get("type")
        assertion = value.get("assertion")
        if not isinstance(definition_type, str) or not isinstance(assertion, str):
            raise ValueError("definition must include type and assertion")
        if definition_type == "page" and assertion in {"title", "url-fragment"}:
            return value
        if definition_type == "element" and assertion in {
            "visibility",
            "text",
            "value",
            "attribute",
        }:
            return value
        raise ValueError("unsupported assertion definition")


class ModelAssertionResponse(BaseModel):
    assertions: list[ModelAssertionProposal] = Field(default_factory=list)


def select_semantic_assertions(
    raw: dict,
    context: ScenarioContext,
    min_confidence: float,
    max_assertions: int,
) -> list[SemanticAssertion]:
    try:
        response = ModelAssertionResponse.model_validate(raw)
    except ValidationError:
        return []

    selected: list[SemanticAssertion] = []
    seen: set[tuple[str, str]] = set()
    valid_state_ids = {state.db_id for state in context.states}
    final_state_id = context.final_state.db_id

    for proposal in sorted(
        response.assertions,
        key=lambda candidate: candidate.confidence,
        reverse=True,
    ):
        if len(selected) >= max_assertions:
            break
        if proposal.confidence < min_confidence:
            continue
        if proposal.targetStateDbId not in valid_state_ids:
            continue
        definition = _normalized_definition(
            proposal.definition, proposal.targetStateDbId
        )
        if not definition:
            continue

        dedupe_key = (definition["type"], definition.get("assertion", ""))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        assertion_id = _assertion_id(context, proposal, definition)
        selected.append(
            SemanticAssertion(
                id=assertion_id,
                db_id=f"semantic:scenario:{context.index}:{assertion_id}",
                label=proposal.label,
                description=proposal.description
                or "Validates the complete scenario outcome.",
                target_state_db_id=proposal.targetStateDbId or final_state_id,
                context_id=f"scenario:{context.index}",
                severity=proposal.severity,
                definition=definition,
                semantic={
                    "scope": "scenario",
                    "source": "model",
                    "confidence": proposal.confidence,
                    "reason": proposal.reason,
                    "contextTransitionDbId": proposal.contextTransitionDbId,
                },
            )
        )

    return selected


def _normalized_definition(
    definition: dict[str, Any], target_state_db_id: str
) -> dict[str, Any]:
    definition_type = definition.get("type")
    assertion = definition.get("assertion")
    if definition_type == "page" and assertion == "title":
        expected_text = _stable_text(definition.get("expectedText"))
        return (
            {"type": "page", "assertion": "title", "expectedText": expected_text}
            if expected_text
            else {}
        )
    if definition_type == "page" and assertion == "url-fragment":
        fragment = _stable_text(definition.get("expectedFragment"))
        return (
            {"type": "page", "assertion": "url-fragment", "expectedFragment": fragment}
            if fragment
            else {}
        )
    if definition_type != "element":
        return {}

    locator_key = _stable_text(definition.get("locatorKey"))
    locator = (
        definition.get("locator")
        if isinstance(definition.get("locator"), dict)
        else None
    )
    if not locator_key and not locator:
        return {}

    base = {
        "type": "element",
        "assertion": assertion,
        "stateId": target_state_db_id,
    }
    if locator_key:
        base["locatorKey"] = locator_key
        if not locator:
            base["locator"] = {"cssSelector": locator_key}
    if locator:
        base["locator"] = locator

    if assertion == "visibility":
        return {**base, "visible": bool(definition.get("visible", True))}
    if assertion == "text":
        expected_text = _stable_text(definition.get("expectedText"))
        return {**base, "expectedText": expected_text} if expected_text else {}
    if assertion == "value":
        expected_value = _stable_text(definition.get("expectedValue"))
        return {**base, "expectedValue": expected_value} if expected_value else {}
    if assertion == "attribute":
        name = _stable_text(definition.get("attributeName"))
        value = _stable_text(definition.get("expectedValue"))
        return (
            {**base, "attributeName": name, "expectedValue": value}
            if name and value
            else {}
        )
    return {}


def _stable_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned or VOLATILE_TEXT.search(cleaned):
        return ""
    return cleaned


def _assertion_id(
    context: ScenarioContext,
    proposal: ModelAssertionProposal,
    definition: dict[str, Any],
) -> str:
    target = next(
        (
            state.name
            for state in context.states
            if state.db_id == proposal.targetStateDbId
        ),
        context.final_state.name,
    )
    stem = " ".join(
        _compact_id_parts(
            target,
            definition,
        )
    )
    return f"A_{upper_snake(stem, f'ASSERTION_{context.index + 1}')}"


def _compact_id_parts(target: str, definition: dict[str, Any]) -> list[str]:
    target_tokens = _significant_words(target)
    assertion = definition.get("assertion", "")
    if definition.get("type") == "page":
        return [*target_tokens[:2], assertion.replace("-", " ")]

    locator = definition.get("locatorKey") or ""
    expected = (
        definition.get("expectedText")
        or definition.get("expectedValue")
        or definition.get("attributeName")
        or ""
    )
    parts = [
        *target_tokens[:2],
        *_significant_words(locator)[:2],
        *_significant_words(expected)[:2],
        assertion.replace("-", " "),
    ]
    return parts[:6] or [assertion]


def _significant_words(value: str) -> list[str]:
    ignored = {
        "a",
        "after",
        "and",
        "are",
        "be",
        "clicking",
        "displayed",
        "for",
        "is",
        "link",
        "on",
        "page",
        "that",
        "the",
        "to",
        "user",
        "verify",
    }
    return [
        word
        for word in re.findall(r"[A-Za-z0-9]+", value or "")
        if word.lower() not in ignored
    ]
