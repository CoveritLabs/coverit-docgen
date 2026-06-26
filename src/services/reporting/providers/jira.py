"""Jira Cloud implementation of IssueProvider.

All Jira-specific concerns (ADF formatting, multipart attachment quirks,
auth header shape) live here.
"""

import re
import uuid
from urllib.parse import quote

from src.core.http_client import json_request, multipart_file, raw_request
from .base import CreatedIssue, IssueProvider, ProviderError

JIRA_API_BASE = "https://api.atlassian.com/ex/jira"


class JiraProvider(IssueProvider):
    name = "jira"

    async def create_issue(self, context: dict) -> CreatedIssue:
        payload = {
            "fields": {
                "project": {"id": context["reportingConfig"]["project"]["id"]},
                "issuetype": {"id": context["reportingConfig"]["issueType"]["id"]},
                "summary": self._jira_summary(context["report"]["title"]),
                "description": self._adf_description(context["structuredDescription"]),
                "labels": self._labels(context),
            }
        }
        access = context["access"]
        try:
            _, data = await json_request(
                "POST",
                f"{JIRA_API_BASE}/{access['cloudId']}/rest/api/3/issue",
                payload,
                self._auth_headers(access),
            )
        except RuntimeError as exc:
            raise ProviderError(f"jira: failed to create issue: {exc}") from exc

        key = data["key"]
        return CreatedIssue(key=key, id=data.get("id"), url=self.issue_url(context, key))

    async def upload_attachment(
        self,
        context: dict,
        issue_key: str,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> None:
        access = context["access"]
        boundary = f"coverit-{uuid.uuid4().hex}"
        body = multipart_file(boundary, "file", filename, content, content_type)
        headers = self._auth_headers(access)
        headers.update(
            {
                "X-Atlassian-Token": "no-check",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }
        )
        try:
            await raw_request(
                "POST",
                f"{JIRA_API_BASE}/{access['cloudId']}/rest/api/3/issue/{quote(issue_key)}/attachments",
                body,
                headers,
            )
        except RuntimeError as exc:
            raise ProviderError(f"jira: failed to upload attachment '{filename}': {exc}") from exc

    def issue_url(self, context: dict, issue_key: str) -> str | None:
        site_url = context["access"].get("siteUrl")
        if not site_url:
            return None
        return f"{site_url.rstrip('/')}/browse/{issue_key}"

    @staticmethod
    def _auth_headers(access: dict) -> dict[str, str]:
        return {
            "Authorization": f"{access['tokenType']} {access['accessToken']}",
            "Accept": "application/json",
        }

    @staticmethod
    def _adf_description(structured_description: dict) -> dict:
        """Transform the structured report description into Atlassian Document Format."""
        blocks = structured_description.get("blocks", [])
        footer = structured_description.get("footer")
        paragraphs = [
            block.get("text") or " "
            for block in blocks
            if block.get("type") == "paragraph"
        ]
        if not paragraphs:
            paragraphs.append(structured_description.get("summary") or " ")

        return {
            "type": "doc",
            "version": 1,
            "content": [
                *[JiraProvider._adf_paragraph(line) for line in paragraphs],
                *([JiraProvider._adf_footer(footer)] if footer else []),
            ],
        }

    @staticmethod
    def _labels(context: dict) -> list[str]:
        labels = ["coverit"]
        application_name = context.get("applicationName") or context.get("application_name")
        application_slug = JiraProvider._label_slug(application_name)
        if application_slug:
            labels.append(f"coverit-app-{application_slug}"[:255])
        return labels

    @staticmethod
    def _jira_summary(value: object) -> str:
        if not isinstance(value, str):
            return "Untitled report"
        first_line = value.strip().splitlines()[0] if value.strip() else ""
        summary = re.sub(r"\s+", " ", first_line).strip()
        return summary[:255] or "Untitled report"

    @staticmethod
    def _label_slug(value: object) -> str:
        if not isinstance(value, str):
            return ""
        slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
        return re.sub(r"-{2,}", "-", slug)

    @staticmethod
    def _adf_paragraph(text: str) -> dict:
        content = []
        lines = (text or " ").splitlines()
        if not lines:
            lines = [" "]
        for index, line in enumerate(lines):
            if index > 0:
                content.append({"type": "hardBreak"})
            if line:
                content.append({"type": "text", "text": line})
            elif index == 0 and len(lines) == 1:
                content.append({"type": "text", "text": " "})
        if not content or all(item.get("type") == "hardBreak" for item in content):
            content.append({"type": "text", "text": " "})
        return {
            "type": "paragraph",
            "content": content,
        }

    @staticmethod
    def _adf_footer(text: str) -> dict:
        return {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": text,
                    "marks": [
                        {"type": "em"},
                        {"type": "textColor", "attrs": {"color": "#626F86"}},
                    ],
                }
            ],
        }
