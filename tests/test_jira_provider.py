import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.services.reporting.providers.jira import JiraProvider


class JiraProviderTests(unittest.TestCase):
    def test_labels_include_coverit_and_safe_application_slug(self):
        self.assertEqual(
            JiraProvider._labels({"applicationName": "My Shop!"}),
            ["coverit", "coverit-app-my-shop"],
        )

    def test_labels_omit_application_label_when_name_is_missing(self):
        self.assertEqual(JiraProvider._labels({}), ["coverit"])

    def test_create_issue_payload_includes_labels(self):
        context = {
            "access": {
                "tokenType": "Bearer",
                "accessToken": "access-token",
                "cloudId": "cloud-1",
                "siteUrl": "https://site.atlassian.net",
            },
            "reportingConfig": {
                "project": {"id": "10000"},
                "issueType": {"id": "10001"},
            },
            "report": {"title": "Checkout failed"},
            "structuredDescription": {"summary": "Checkout failed", "blocks": []},
            "applicationName": "My Shop!",
        }

        with patch("src.services.reporting.providers.jira.json_request", new_callable=AsyncMock) as json_request:
            json_request.return_value = (201, {"key": "COV-1", "id": "issue-1"})

            asyncio.run(JiraProvider().create_issue(context))

        payload = json_request.await_args.args[2]
        self.assertEqual(payload["fields"]["labels"], ["coverit", "coverit-app-my-shop"])

    def test_create_issue_payload_removes_newlines_from_summary(self):
        context = {
            "access": {
                "tokenType": "Bearer",
                "accessToken": "access-token",
                "cloudId": "cloud-1",
                "siteUrl": "https://site.atlassian.net",
            },
            "reportingConfig": {
                "project": {"id": "10000"},
                "issueType": {"id": "10001"},
            },
            "report": {"title": "Checkout failed\nButton never submits"},
            "structuredDescription": {"summary": "Checkout failed\nButton never submits", "blocks": []},
        }

        with patch("src.services.reporting.providers.jira.json_request", new_callable=AsyncMock) as json_request:
            json_request.return_value = (201, {"key": "COV-1", "id": "issue-1"})

            asyncio.run(JiraProvider().create_issue(context))

        payload = json_request.await_args.args[2]
        self.assertEqual(payload["fields"]["summary"], "Checkout failed")

    def test_adf_description_preserves_frontend_description_text(self):
        description = "\n".join(
            [
                "## Summary",
                "Checkout failed during regression.",
                "",
                "## Result counts",
                "- Passed checks: 4",
                "- Failed checks: 1",
            ]
        )

        adf = JiraProvider._adf_description(
            {
                "summary": description,
                "footer": "Generated automatically by CoverIt.",
                "blocks": [
                    {"key": "description", "type": "paragraph", "title": "Description", "text": description},
                    {"key": "reporter", "type": "metadata", "title": "Reporter", "text": "user@example.com"},
                ],
            }
        )

        self.assertEqual(
            adf["content"][0],
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "## Summary"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Checkout failed during regression."},
                    {"type": "hardBreak"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "## Result counts"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "- Passed checks: 4"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "- Failed checks: 1"},
                ],
            },
        )
        self.assertNotIn("user@example.com", str(adf))

    def test_adf_description_renders_worker_footer_as_deemphasized_italic_text(self):
        adf = JiraProvider._adf_description(
            {
                "summary": "Broken checkout",
                "footer": "Generated automatically by CoverIt.",
                "blocks": [
                    {"key": "description", "type": "paragraph", "title": "Description", "text": "Broken checkout"}
                ],
            }
        )

        self.assertEqual(
            adf["content"][-1],
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Generated automatically by CoverIt.",
                        "marks": [
                            {"type": "em"},
                            {"type": "textColor", "attrs": {"color": "#626F86"}},
                        ],
                    }
                ],
            },
        )

    def test_adf_description_uses_summary_when_no_paragraph_block_exists(self):
        adf = JiraProvider._adf_description(
            {
                "summary": "Fallback report summary",
                "footer": "",
                "blocks": [{"key": "source", "type": "metadata", "title": "Source", "text": "CoverIt"}],
            }
        )

        self.assertEqual(
            adf["content"],
            [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Fallback report summary"}],
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
