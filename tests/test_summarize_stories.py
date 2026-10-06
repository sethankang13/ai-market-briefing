import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import summarize_stories


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


class SummarizeStoriesTests(unittest.TestCase):
    def test_mock_summary_uses_headline(self):
        self.assertEqual(
            summarize_stories.mock_summary("Rates rise"),
            "[AI Summary Pending: Rates rise]",
        )

    def test_no_keys_uses_mock_without_http(self):
        story = sample_story()
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(summarize_stories, "_post_json") as post_json:
                summary, provider = summarize_stories.summarize_story(story)

        self.assertEqual(provider, "mock")
        self.assertEqual(summary, "[AI Summary Pending: Oil prices jump]")
        post_json.assert_not_called()

    def test_gemini_is_preferred_when_key_is_set(self):
        story = sample_story()
        gemini_body = {
            "candidates": [{"content": {"parts": [{"text": "Oil supply news may move energy prices."}]}}]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"}):
            with patch.object(summarize_stories, "_post_json", return_value=gemini_body) as post_json:
                summary, provider = summarize_stories.summarize_story(story)

        self.assertEqual(provider, "gemini")
        self.assertEqual(summary, "Oil supply news may move energy prices.")
        self.assertIn("generativelanguage.googleapis.com", post_json.call_args.args[0])
        self.assertIn("gemini-3.8-flash", post_json.call_args.args[0])
        self.assertEqual(post_json.call_args.args[2]["x-goog-api-key"], "gemini-test")
        self.assertNotIn("key=", post_json.call_args.args[0])

    def test_gemini_skips_thought_parts(self):
        story = sample_story()
        gemini_body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "internal reasoning"},
                            {"text": "Oil headlines can shift energy expectations."},
                        ]
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "_post_json", return_value=gemini_body):
                summary, provider = summarize_stories.summarize_story(story)

        self.assertEqual(provider, "gemini")
        self.assertEqual(summary, "Oil headlines can shift energy expectations.")

    def test_openai_is_used_when_gemini_key_is_absent(self):
        story = sample_story()
        openai_body = {
            "choices": [{"message": {"content": "Traders may watch crude inventories."}}]
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test"}, clear=True):
            with patch.object(summarize_stories, "_post_json", return_value=openai_body) as post_json:
                summary, provider = summarize_stories.summarize_story(story)

        self.assertEqual(provider, "openai")
        self.assertEqual(summary, "Traders may watch crude inventories.")
        self.assertEqual(post_json.call_args.args[0], summarize_stories.OPENAI_URL)
        self.assertEqual(post_json.call_args.args[1]["model"], "gpt-4o-mini")

    def test_gemini_failure_falls_back_to_openai(self):
        story = sample_story()
        openai_body = {
            "choices": [{"message": {"content": "Fallback interpretation of the oil headline."}}]
        }

        def fake_post(url, payload, headers, timeout=30):
            if "generativelanguage" in url:
                raise ValueError("Gemini unavailable")
            return openai_body

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"}):
            with patch.object(summarize_stories, "_post_json", side_effect=fake_post):
                summary, provider = summarize_stories.summarize_story(story)

        self.assertEqual(provider, "openai")
        self.assertIn("Fallback interpretation", summary)

    def test_both_providers_failing_uses_mock(self):
        story = sample_story("Tariffs expand")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"}):
            with patch.object(summarize_stories, "_post_json", side_effect=ValueError("down")):
                summary, provider = summarize_stories.summarize_story(story)

        self.assertEqual(provider, "mock")
        self.assertEqual(summary, "[AI Summary Pending: Tariffs expand]")

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
                            selected_run, selected_path
                        )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(summarized_dir.is_dir())
            self.assertEqual(output_path, summarized_dir / "2026-10-04.json")
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["selected_run"], "2026-10-04.json")
            self.assertEqual(saved["summarizer"], "mock")
            self.assertEqual(
                saved["stories"][0]["ai_summary"],
                "[AI Summary Pending: Oil prices jump]",
            )
            self.assertEqual(saved["stories"][0]["headline"], "Oil prices jump")

    def test_summarize_stories_does_not_mutate_input(self):
        stories = [sample_story()]
        with patch.dict(os.environ, {}, clear=True):
            summarized, provider = summarize_stories.summarize_stories(stories)

        self.assertEqual(provider, "mock")
        self.assertNotIn("ai_summary", stories[0])
        self.assertIn("ai_summary", summarized[0])


if __name__ == "__main__":
    unittest.main()
