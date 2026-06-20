import re
from urllib.parse import urlparse

def parse_cron_string(cron_str: str) -> set[int]:
    if not cron_str or cron_str.strip() == "*":
        return None  # ARQ treats None as "every minute"
    return {int(x.strip()) for x in cron_str.split(",")}


def words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", value)


def title(value: str) -> str:
    return " ".join(word.capitalize() for word in words(value))


def upper_snake(value: str, fallback: str) -> str:
    return "_".join(word.upper() for word in words(value)) or fallback


def pascal(value: str) -> str:
    return "".join(word.capitalize() for word in words(value))


def slug(value: str) -> str:
    return "-".join(word.lower() for word in words(value)) or "state"


def url_area(url: str) -> str:
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments:
        return segments[0].lower()
    if parsed.hostname:
        return parsed.hostname.split(".")[0].lower()
    return ""


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
