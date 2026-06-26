"""The abstraction the worker depends on, instead of any concrete tracker.

Add a new provider (Jira, Azure DevOps, GitHub Issues...) by subclassing
IssueProvider and registering it in registry.py. The worker never changes.
"""

from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Base class for provider-specific failures. Lets the worker log/handle
    provider failures uniformly without knowing which provider raised them."""


class CreatedIssue:
    __slots__ = ("key", "id", "url")

    def __init__(self, key: str, id: str | None, url: str | None) -> None:
        self.key = key
        self.id = id
        self.url = url


class IssueProvider(ABC):
    """One external issue tracker integration."""

    name: str

    @abstractmethod
    async def create_issue(self, context: dict) -> CreatedIssue:
        """Create an external issue from a report context. Raise ProviderError
        (or let underlying errors propagate) on failure."""

    @abstractmethod
    async def upload_attachment(
        self,
        context: dict,
        issue_key: str,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> None:
        """Attach a single artifact to an already-created issue."""

    @abstractmethod
    def issue_url(self, context: dict, issue_key: str) -> str | None:
        """Build a human-viewable URL for an existing issue, if possible."""
