import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import archived_article_summarizer as archived


ARTICLE = (
    "Oil prices rose after the inventory report showed a tighter crude market. "
    "Traders quoted in the article pointed to shipping delays."
)


class ArchivedArticleSummarizerTests(unittest.TestCase):
    def test_module_docstring_marks_the_path_as_archived(self):
        self.assertIn("Reserved for a future paywall", archived.__doc__)
        self.assertIn("must not import or call this module", archived.__doc__)

    def test_extract_article_text_prefers_the_article_element(self):
        html = """
        <html><body>
          <nav>Menu item</nav>
          <article>
            <p>Oil prices rose after the inventory report showed a tighter crude market.</p>
            <script>ignore this script</script>
          </article>
        </body></html>
        """
        text = archived.extract_article_text(html)
        self.assertIn("tighter crude market", text)
        self.assertNotIn("Menu item", text)
        self.assertNotIn("ignore this script", text)

    def test_read_article_caps_long_text(self):
        paragraph = "inventory " * 4000
        html = f"<article><p>{paragraph}</p></article>"
        with patch.object(archived, "fetch_html", return_value=html):
            text, article_read = archived.read_article("https://example.com/story")

        self.assertTrue(article_read)
        self.assertLessEqual(
            len(text),
            archived.MAX_ARTICLE_CHARS + len("\n[Article text truncated]"),
        )
        self.assertTrue(text.endswith("[Article text truncated]"))

    def test_read_article_failure_is_not_treated_as_read(self):
        with patch.object(archived, "fetch_html", side_effect=URLError("down")):
            text, article_read = archived.read_article("https://example.com/story")

        self.assertIsNone(text)
        self.assertFalse(article_read)
        self.assertEqual(archived.read_article("not a url"), (None, False))

    def test_short_extract_counts_as_not_read(self):
        with patch.object(
            archived, "fetch_html", return_value="<article><p>Hi</p></article>"
        ):
            text, article_read = archived.read_article("https://example.com/story")

        self.assertIsNone(text)
        self.assertFalse(article_read)


if __name__ == "__main__":
    unittest.main()
