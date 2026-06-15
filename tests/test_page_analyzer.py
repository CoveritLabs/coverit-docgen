import unittest

from bs4 import BeautifulSoup

from src.services.labeling.page_analyzer import get_page_info


class PageAnalyzerTests(unittest.TestCase):
    def analyze(self, url: str, html: str = ""):
        return get_page_info(url, BeautifulSoup(html, "html.parser"))

    def test_semantic_path_has_highest_priority(self):
        result = self.analyze(
            "https://www.example.com/settings/profile",
            "<title>Profile | Example</title><h1>Edit Profile</h1>",
        )
        self.assertEqual(result["name"], "Settings > Profile")
        self.assertEqual(result["description"], "Edit Profile")

    def test_opaque_path_segments_are_ignored(self):
        result = self.analyze(
            "https://example.com/users/43829/"
            "550e8400-e29b-41d4-a716-446655440000"
        )
        self.assertEqual(result["name"], "Users")

    def test_query_and_fragment_are_semantic_signals(self):
        result = self.analyze(
            "https://example.com/settings?tab=security#billing"
        )
        self.assertEqual(
            result["name"],
            "Settings > Security tab > Billing section",
        )

    def test_tracking_pagination_and_sorting_are_ignored(self):
        result = self.analyze(
            "https://example.com/orders?page=2&sort=date&utm_source=email"
        )
        self.assertEqual(result["name"], "Orders")

    def test_title_suffix_is_removed_for_root_page(self):
        result = self.analyze(
            "https://coverit.com/",
            "<title>Analytics Dashboard | Coverit</title>",
        )
        self.assertEqual(result["name"], "Analytics Dashboard")

    def test_semantic_title_suffix_is_preserved(self):
        result = self.analyze(
            "https://example.com/",
            "<title>Account - Security Settings</title>",
        )
        self.assertEqual(result["name"], "Account - Security Settings")

    def test_company_title_suffix_is_removed(self):
        result = self.analyze(
            "https://acme.com/",
            "<title>Billing - Acme Corporation</title>",
        )
        self.assertEqual(result["name"], "Billing")

    def test_open_graph_description_precedes_meta_description(self):
        result = self.analyze(
            "https://example.com/profile",
            """
            <meta property="og:description" content="Open Graph summary.">
            <meta name="description" content="Meta summary.">
            """,
        )
        self.assertEqual(result["description"], "Open Graph summary.")

    def test_active_navigation_can_name_a_root_page(self):
        result = self.analyze(
            "https://example.com/",
            '<nav><a aria-current="page">Reports</a></nav>',
        )
        self.assertEqual(result["name"], "Reports")

    def test_duplicate_heading_is_not_repeated_as_description(self):
        result = self.analyze(
            "https://example.com/dashboard",
            "<h1>Dashboard</h1>",
        )
        self.assertIsNone(result["description"])

    def test_description_is_one_sentence_and_capped(self):
        long_text = " ".join(["Detailed"] * 40)
        result = self.analyze(
            "https://example.com/reports",
            f'<meta name="description" content="{long_text}">',
        )
        self.assertLessEqual(len(result["description"]), 160)
        self.assertTrue(result["description"].endswith("…"))


if __name__ == "__main__":
    unittest.main()
