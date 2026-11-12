"""Static checks on the web files that are easy to break by hand."""

from __future__ import annotations

import re
import unittest

from tests.support import ROOT

WEB = ROOT / "web"
STYLES = (WEB / "css" / "styles.css").read_text(encoding="utf-8")
PAGES = sorted(WEB.glob("*.html"))
# Tokens that are the same in every theme.
THEME_INDEPENDENT = {"--radius", "--font", "--font-display"}


def tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block))


def block_after(selector: str) -> str:
    start = STYLES.index(selector)
    return STYLES[STYLES.index("{", start) + 1 : STYLES.index("}", start)]


class ThemeTest(unittest.TestCase):
    def test_every_colour_token_has_a_dark_value(self) -> None:
        light = set(tokens(block_after(":root {"))) - THEME_INDEPENDENT
        system_dark = set(tokens(block_after(':root:not([data-theme="light"])')))
        pinned_dark = set(tokens(block_after(':root[data-theme="dark"] {')))
        self.assertEqual(light - system_dark, set(), "missing in the prefers-color-scheme block")
        self.assertEqual(light - pinned_dark, set(), "missing in the data-theme block")

    def test_both_dark_blocks_agree(self) -> None:
        self.assertEqual(
            tokens(block_after(':root:not([data-theme="light"])')),
            tokens(block_after(':root[data-theme="dark"] {')),
        )

    def test_every_page_loads_the_theme_before_painting(self) -> None:
        self.assertGreaterEqual(len(PAGES), 6)
        for page in PAGES:
            with self.subTest(page=page.name):
                html = page.read_text(encoding="utf-8")
                head = html.split("</head>", 1)[0]
                self.assertIn('<script src="/js/theme.js"></script>', head)
                self.assertIn('name="color-scheme" content="light dark"', head)
                self.assertIn("data-theme-toggle", html)


if __name__ == "__main__":
    unittest.main()
