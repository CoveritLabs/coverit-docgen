import re

from src.models.guides import ResolvedGuidePath


def _clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"([.!?]){2,}", r"\1", value)
    return value


def _sentence(value: str) -> str:
    value = _clean_text(value)
    if not value:
        return ""
    if value[-1] in ".!?":
        return value
    return f"{value}."


def format_user_guide(path: ResolvedGuidePath) -> str:
    """Render a deterministic, user-facing guide from a labeled graph path."""
    start_name = _clean_text(path.start_state.name)
    end_name = _clean_text(path.end_state.name)
    lines = [_sentence(f"Start on the {start_name}")]

    start_description = _sentence(path.start_state.description)
    if start_description:
        lines.append(start_description)

    for index, transition in enumerate(path.transitions, start=1):
        destination = _clean_text(transition.to_state.name)
        
        # Split the action string by ' then ' (case-insensitive) to find sub-steps
        raw_action = transition.action or ""
        sub_actions = re.split(r'\s+then\s+', raw_action, flags=re.IGNORECASE)
        
        # Clean up and format each sub-action into a proper sentence
        sub_actions = [_sentence(sa) for sa in sub_actions if sa.strip()]

        if len(sub_actions) > 1:
            # Decompose into a main step with sub-steps
            lines.append(f"{index}. Do the following to reach the {destination}:")
            for sub_index, sub_action in enumerate(sub_actions, start=1):
                lines.append(f"   {index}.{sub_index} {sub_action}")
        else:
            # Single action: keep the original format
            action = sub_actions[0] if sub_actions else ""
            if action:
                lines.append(f"{index}. {action} This takes you to the {destination}.")
            else:
                # Fallback if an action description is missing
                lines.append(f"{index}. Navigate to the {destination}.")

    lines.append(_sentence(f"You should now be on the {end_name}"))
    return "\n".join(line for line in lines if line).strip()