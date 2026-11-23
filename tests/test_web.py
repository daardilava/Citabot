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


class SearchEngineTest(unittest.TestCase):
    PUBLIC = ("index.html", "precios.html", "login.html", "registro.html")
    PRIVATE = ("app.html", "404.html")

    def head(self, name: str) -> str:
        return (WEB / name).read_text(encoding="utf-8").split("</head>", 1)[0]

    def test_public_pages_describe_themselves_and_stay_indexable(self) -> None:
        for name in self.PUBLIC:
            with self.subTest(page=name):
                head = self.head(name)
                self.assertRegex(head, r'<meta name="description" content="[^"]{50,160}" />')
                self.assertNotIn('name="robots"', head)

    def test_marketing_pages_have_social_previews(self) -> None:
        for name in ("index.html", "precios.html"):
            with self.subTest(page=name):
                head = self.head(name)
                for prop in ("og:title", "og:description", "og:type", "og:locale"):
                    self.assertIn(f'property="{prop}"', head)

    def test_the_panel_and_the_404_page_are_not_indexed(self) -> None:
        for name in self.PRIVATE:
            with self.subTest(page=name):
                self.assertIn('<meta name="robots" content="noindex" />', self.head(name))

    def test_robots_txt_keeps_crawlers_out_of_the_api_only(self) -> None:
        rules = (WEB / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Disallow: /api/", rules)
        # Blocking /app would hide its noindex tag from crawlers.
        self.assertNotRegex(rules, r"Disallow: /app")


if __name__ == "__main__":
    unittest.main()
