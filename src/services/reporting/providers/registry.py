"""Single point where concrete providers get registered."""

from .base import IssueProvider
from .jira import JiraProvider


class UnknownProviderError(Exception):
    pass


_PROVIDERS: dict[str, IssueProvider] = {
    "jira": JiraProvider(),
}


def get_provider(name: str) -> IssueProvider:
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise UnknownProviderError(f"no issue provider registered for '{name}'") from None
