import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import summarize_stories


ARTICLE = (
    "Oil prices rose after the inventory report showed a tighter crude market. "
    "Traders quoted in the article pointed to shipping delays."
)


def sample_story(headline: str = "Oil prices jump") -> dict[str, object]:
    return {
        "headline": headline,
        "source": "Example News",
        "link": "https://example.com/story",
        "published_at": "Today",
        "topics": ["oil", "energy"],
        "selection_score": 8,
        "selection_reason": "Matched: oil, energy.",
    }


def model_json(headline: str, summary: str) -> str:
    return json.dumps({"ai_headline": headline, "ai_summary": summary})


def gemini_body(text: str) -> dict[str, object]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class SummarizeStoriesTests(unittest.TestCase):
    def setUp(self):
        self.env_loader = patch.object(summarize_stories, "load_project_env")
        self.env_loader.start()

    def tearDown(self):
        self.env_loader.stop()

    def test_load_project_env_fills_missing_names_without_overriding(self):
        self.env_loader.stop()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                env_file = Path(temp_dir) / ".env"
                env_file.write_text(
                    "\n".join(
                        [
                            "# comment",
                            "GEMINI_API_KEY=from-file",
                            "OPENAI_API_KEY=from-file",
                            "export ALREADY_SET=from-file",
                        ]
                    ),
                    encoding="utf-8",
                )
                with patch.dict(os.environ, {"ALREADY_SET": "from-shell"}, clear=True):
                    summarize_stories.load_project_env(env_file)
                    self.assertEqual(os.environ["GEMINI_API_KEY"], "from-file")
                    self.assertEqual(os.environ["OPENAI_API_KEY"], "from-file")
                    self.assertEqual(os.environ["ALREADY_SET"], "from-shell")
        finally:
            self.env_loader.start()

    def test_mock_summary_uses_headline(self):
        self.assertEqual(
            summarize_stories.mock_summary("Rates rise"),
            "Mock interpretation of Rates rise.",
        )
        self.assertEqual(
            summarize_stories.mock_headline("Rates rise"),
            "Mock significance headline — Rates rise",
        )
        self.assertNotIn("AI Summary Pending", summarize_stories.mock_summary("Rates rise"))
        self.assertNotIn("AI Headline Pending", summarize_stories.mock_headline("Rates rise"))

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
        text = summarize_stories.extract_article_text(html)
        self.assertIn("tighter crude market", text)
        self.assertNotIn("Menu item", text)
        self.assertNotIn("ignore this script", text)

    def test_read_article_caps_long_text(self):
        paragraph = "inventory " * 4000
        html = f"<article><p>{paragraph}</p></article>"
        with patch.object(summarize_stories, "fetch_html", return_value=html):
            text, article_read = summarize_stories.read_article("https://example.com/story")

        self.assertTrue(article_read)
        self.assertLessEqual(len(text), summarize_stories.MAX_ARTICLE_CHARS + len("\n[Article text truncated]"))
        self.assertTrue(text.endswith("[Article text truncated]"))

    def test_read_article_failure_is_not_treated_as_read(self):
        with patch.object(summarize_stories, "fetch_html", side_effect=URLError("down")):
            text, article_read = summarize_stories.read_article("https://example.com/story")

        self.assertIsNone(text)
        self.assertFalse(article_read)
        self.assertEqual(summarize_stories.read_article("not a url"), (None, False))

    def test_short_extract_counts_as_not_read(self):
        with patch.object(summarize_stories, "fetch_html", return_value="<article><p>Hi</p></article>"):
            text, article_read = summarize_stories.read_article("https://example.com/story")

        self.assertIsNone(text)
        self.assertFalse(article_read)

    def test_no_keys_raises_instead_of_writing_pending_copy(self):
        story = sample_story()
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(summarize_stories, "story_body", return_value=(ARTICLE, True)):
                with patch.object(summarize_stories, "_post_json") as post_json:
                    with self.assertRaises(summarize_stories.SummarizationError):
                        summarize_stories.summarize_story(story)
        post_json.assert_not_called()

    def test_gemini_receives_article_text(self):
        story = sample_story()
        gemini_response = gemini_body(
            model_json("Oil supply is harder to price", "Oil supply news may move energy prices.")
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"}):
            with patch.object(summarize_stories, "story_body", return_value=(ARTICLE, True)):
                with patch.object(summarize_stories, "_post_json", return_value=gemini_response) as post_json:
                    result = summarize_stories.summarize_story(story)

        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.ai_headline, "Oil supply is harder to price")
        self.assertEqual(result.ai_summary, "Oil supply news may move energy prices.")
        self.assertTrue(result.article_read)
        prompt = post_json.call_args.args[1]["contents"][0]["parts"][0]["text"]
        self.assertIn("Article text:", prompt)
        self.assertIn("shipping delays", prompt)
        self.assertNotIn("The article was not read", prompt)
        self.assertIn("not on the headline alone", prompt)
        self.assertIn("generativelanguage.googleapis.com", post_json.call_args.args[0])
        self.assertIn("gemini-3.8-flash", post_json.call_args.args[0])
        self.assertEqual(post_json.call_args.args[2]["x-goog-api-key"], "gemini-test")
        self.assertNotIn("key=", post_json.call_args.args[0])
        self.assertEqual(
            post_json.call_args.args[1]["generationConfig"],
            {"maxOutputTokens": 1024, "thinkingConfig": {"thinkingLevel": "low"}},
        )

    def test_unread_article_is_labeled_and_not_invented(self):
        story = sample_story()
        gemini_response = gemini_body(
            model_json("Headline only", "This uses the headline because the page was unavailable.")
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "story_body", return_value=(None, False)):
                with patch.object(summarize_stories, "_post_json", return_value=gemini_response) as post_json:
                    result = summarize_stories.summarize_story(story)

        prompt = post_json.call_args.args[1]["contents"][0]["parts"][0]["text"]
        self.assertFalse(result.article_read)
        self.assertIn("The article was not read", prompt)
        self.assertNotIn("Article text:", prompt)
        self.assertNotIn("shipping delays", prompt)

    def test_gemini_skips_thought_parts(self):
        story = sample_story()
        gemini_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "internal reasoning"},
                            {
                                "text": model_json(
                                    "Oil expectations shifted",
                                    "Oil headlines can shift energy expectations.",
                                )
                            },
                        ]
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "story_body", return_value=(ARTICLE, True)):
                with patch.object(summarize_stories, "_post_json", return_value=gemini_response):
                    result = summarize_stories.summarize_story(story)

        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.ai_summary, "Oil headlines can shift energy expectations.")
        self.assertNotIn("internal reasoning", result.ai_summary)

    def test_openai_is_used_when_gemini_key_is_absent(self):
        story = sample_story()
        openai_body = {
            "choices": [
                {
                    "message": {
                        "content": model_json(
                            "Inventories are the watch item",
                            "Traders may watch crude inventories.",
                        )
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test"}, clear=True):
            with patch.object(summarize_stories, "story_body", return_value=(ARTICLE, True)):
                with patch.object(summarize_stories, "_post_json", return_value=openai_body) as post_json:
                    result = summarize_stories.summarize_story(story)

        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.ai_headline, "Inventories are the watch item")
        self.assertEqual(result.ai_summary, "Traders may watch crude inventories.")
        self.assertEqual(post_json.call_args.args[0], summarize_stories.OPENAI_URL)
        self.assertEqual(post_json.call_args.args[1]["model"], "gpt-4o-mini")
        self.assertIn("shipping delays", post_json.call_args.args[1]["messages"][1]["content"])

    def test_gemini_failure_falls_back_to_openai(self):
        story = sample_story()
        openai_body = {
            "choices": [
                {
                    "message": {
                        "content": model_json(
                            "Fallback headline",
                            "Fallback interpretation of the oil headline.",
                        )
                    }
                }
            ]
        }

        def fake_post(url, payload, headers, timeout=30):
            if "generativelanguage" in url:
                raise ValueError("Gemini unavailable")
            return openai_body

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"}):
            with patch.object(summarize_stories, "story_body", return_value=(None, False)):
                with patch.object(summarize_stories, "_post_json", side_effect=fake_post):
                    result = summarize_stories.summarize_story(story)

        self.assertEqual(result.provider, "openai")
        self.assertIn("Fallback interpretation", result.ai_summary)
        self.assertFalse(result.article_read)

    def test_both_providers_failing_raises(self):
        story = sample_story("Tariffs expand")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"}):
            with patch.object(summarize_stories, "story_body", return_value=(None, False)):
                with patch.object(summarize_stories, "_post_json", side_effect=ValueError("down")):
                    with self.assertRaises(summarize_stories.SummarizationError):
                        summarize_stories.summarize_story(story)

    def test_gemini_cascade_skips_429_then_uses_next_model(self):
        story = sample_story()
        gemini_response = gemini_body(
            model_json("Supply tightened", "A tighter crude market may reprice energy.")
        )
        calls = []

        def fake_post(url, payload, headers, timeout=30):
            calls.append(url)
            if "gemini-3.8-flash" in url:
                raise urllib.error.HTTPError(url, 429, "quota", {}, None)
            if "gemini-3.7-flash" in url:
                return gemini_response
            raise AssertionError(f"unexpected url {url}")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "story_body", return_value=(ARTICLE, True)):
                with patch.object(summarize_stories, "_post_json", side_effect=fake_post):
                    result = summarize_stories.summarize_story(story)

        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.ai_headline, "Supply tightened")
        self.assertIn("gemini-3.8-flash", calls[0])
        self.assertIn("gemini-3.7-flash", calls[1])

    def test_rss_full_text_is_sent_without_fetching(self):
        story = sample_story()
        story["full_text"] = ARTICLE
        gemini_response = gemini_body(
            model_json("Body-based headline", "The inventory report is the watch item.")
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "read_article") as read_article:
                with patch.object(summarize_stories, "_post_json", return_value=gemini_response) as post_json:
                    result = summarize_stories.summarize_story(story)

        read_article.assert_not_called()
        self.assertTrue(result.article_read)
        prompt = post_json.call_args.args[1]["contents"][0]["parts"][0]["text"]
        self.assertIn("shipping delays", prompt)
        self.assertIn("not on the headline alone", prompt)

    def test_save_creates_summarized_directory_and_ai_summary(self):
        selected_run = {"failed_sources": [], "stories": [sample_story()]}
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = Path.cwd()
            project = Path(temp_dir)
            selected_path = project / "data" / "selected" / "2026-10-04.json"
            selected_path.parent.mkdir(parents=True)
            selected_path.write_text("{}", encoding="utf-8")
            summarized_dir = project / "data" / "summarized"
            os.chdir(project)
            try:
                with patch.object(summarize_stories, "SUMMARIZED_DATA_DIRECTORY", summarized_dir):
                    with patch.dict(os.environ, {}, clear=True):
                        output_path = summarize_stories.save_summarized_run(
                            selected_run, selected_path, mock=True
                        )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(summarized_dir.is_dir())
            self.assertEqual(output_path, summarized_dir / "2026-10-04.json")
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["selected_run"], "2026-10-04.json")
            self.assertEqual(saved["summarizer"], "mock")
            self.assertEqual(
                saved["stories"][0]["ai_headline"],
                "Mock significance headline — Oil prices jump",
            )
            self.assertEqual(
                saved["stories"][0]["ai_summary"],
                "Mock interpretation of Oil prices jump.",
            )
            self.assertNotIn("AI Summary Pending", saved["stories"][0]["ai_summary"])
            self.assertNotIn("AI Headline Pending", saved["stories"][0]["ai_headline"])
            self.assertFalse(saved["stories"][0]["article_read"])
            self.assertEqual(saved["stories"][0]["article_note"], "Article was not read.")
            self.assertEqual(saved["stories"][0]["headline"], "Oil prices jump")

    def test_summarize_stories_does_not_mutate_input(self):
        stories = [sample_story()]
        stories[0]["full_text"] = ARTICLE
        with patch.dict(os.environ, {}, clear=True):
            summarized, provider = summarize_stories.summarize_stories(stories, mock=True)

        self.assertEqual(provider, "mock")
        self.assertNotIn("ai_summary", stories[0])
        self.assertNotIn("ai_headline", stories[0])
        self.assertNotIn("article_read", stories[0])
        self.assertIn("ai_summary", summarized[0])
        self.assertTrue(summarized[0]["article_read"])
        self.assertNotIn("article_note", summarized[0])


if __name__ == "__main__":
    unittest.main()
