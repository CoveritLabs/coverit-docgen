import unittest

from src.services.reporting.providers.jira import JiraProvider


class JiraProviderTests(unittest.TestCase):
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
                "content": [{"type": "text", "text": description}],
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
