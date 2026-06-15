import unittest

from bs4 import BeautifulSoup

from src.services.labeling.labeling import Labeling


def element_at(x, y, width=20, height=20, text="", tag="div"):
    return (
        f'<{tag} data-x="{x}" data-y="{y}" data-width="{width}" '
        f'data-height="{height}">{text}</{tag}>'
    )


class ContextLabelingTests(unittest.TestCase):
    def contextual_name(self, target_markup: str, other_markup: str = ""):
        soup = BeautifulSoup(
            '<body data-x="0" data-y="0" data-width="1000" '
            f'data-height="1000">{target_markup}{other_markup}</body>',
            "html.parser",
        )
        target = soup.find(attrs={"id": "target"})
        return Labeling()._get_name_from_context(target, soup.body)

    def test_close_neighbor_uses_relative_language(self):
        result = self.contextual_name(
            '<input id="target" data-x="300" data-y="100" '
            'data-width="20" data-height="20">',
            element_at(200, 100, text="Search", tag="button"),
        )
        self.assertEqual(result, "to the right of the button 'Search'")

    def test_exact_threshold_remains_relative(self):
        result = self.contextual_name(
            '<input id="target" data-x="490" data-y="90" '
            'data-width="20" data-height="20">',
            element_at(90, 90, text="Submit", tag="button"),
        )
        self.assertEqual(result, "to the right of the button 'Submit'")

    def test_distant_neighbor_uses_absolute_position(self):
        result = self.contextual_name(
            '<input id="target" data-x="880" data-y="490" '
            'data-width="20" data-height="20">',
            element_at(80, 490, text="Search", tag="button"),
        )
        self.assertEqual(result, "on the right side of the screen")

    def test_no_neighbor_uses_absolute_position(self):
        result = self.contextual_name(
            '<input id="target" data-x="490" data-y="490" '
            'data-width="20" data-height="20">'
        )
        self.assertEqual(result, "centered on the screen")

    def test_all_nine_screen_regions(self):
        cases = {
            (100, 100): "in the top-left corner",
            (500, 100): "at the top of the screen",
            (900, 100): "in the top-right corner",
            (100, 500): "on the left side of the screen",
            (500, 500): "centered on the screen",
            (900, 500): "on the right side of the screen",
            (100, 900): "in the bottom-left corner",
            (500, 900): "at the bottom of the screen",
            (900, 900): "in the bottom-right corner",
        }
        for (x, y), expected in cases.items():
            with self.subTest(x=x, y=y):
                result = self.contextual_name(
                    f'<input id="target" data-x="{x - 10}" '
                    f'data-y="{y - 10}" data-width="20" data-height="20">'
                )
                self.assertEqual(result, expected)

    def test_missing_target_geometry_returns_none(self):
        soup = BeautifulSoup('<body><input id="target"></body>', "html.parser")
        self.assertIsNone(
            Labeling()._get_name_from_context(
                soup.find(id="target"),
                soup.body,
            )
        )


if __name__ == "__main__":
    unittest.main()
