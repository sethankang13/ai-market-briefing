import json
import os
import sys
import tempfile
import unittest
import urllib.error
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
        "description": "Inventory report showed a tighter crude market.",
        "tags": ["Market Valuations"],
        "selection_score": 8,
        "selection_reason": "Matched: Market Valuations.",
    }


def sample_history() -> list[dict[str, object]]:
    return [
        {
            "published_date": "2026-10-20",
            "headline": "Chip export rules tighten",
            "source": "Other Source",
            "tags": json.dumps(["Geopolitics & Trade"]),
            "full_text": "Trade controls affect supply.",
        }
    ]


def sample_macro() -> str:
    return (
        "{\n"
        '  "tag_notes": {\n'
        '    "Market Valuations": "Energy headlines cluster around supply constraints."\n'
        "  },\n"
        '  "daily_summary": "Energy and trade headlines cluster around supply constraints.",\n'
        '  "research_radar": ["Crude inventories.", "Chip export licenses.", "Policy follow-through."]\n'
        "}\n"
    )


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

    def test_mock_macro_writes_required_sections_without_pending_copy(self):
        report = summarize_stories.mock_macro_report([sample_story()], [])
        notes, daily, radar = summarize_stories.parse_briefing_copy(report)
        self.assertIn("Market Valuations", notes)
        self.assertIn("Oil prices jump", notes["Market Valuations"])
        self.assertIn("Oil prices jump", daily)
        self.assertGreaterEqual(len(radar), 3)
        self.assertNotIn("AI Summary Pending", report)
        self.assertNotIn("AI Headline Pending", report)
        self.assertNotIn("AI headline pending", report)
        self.assertNotIn("AI Summary goes HERE", report)
        self.assertNotIn("Why It Matters", report)

    def test_parse_briefing_copy_rejects_pending_and_accepts_delimited_sections(self):
        with self.assertRaises(ValueError):
            summarize_stories.parse_briefing_copy(
                '{"daily_summary": "AI Summary Pending", "tag_notes": {}, "research_radar": []}'
            )
        notes, daily, radar = summarize_stories.parse_briefing_copy(
            "## US Politics\n\n"
            "Policy pattern from today's bill.\n\n"
            "## Daily Summary\n\n"
            "What happened today across the selected headlines.\n\n"
            "## Research Radar\n\n"
            "1. Follow the bill markup.\n"
        )
        self.assertEqual(notes["US Politics"], "Policy pattern from today's bill.")
        self.assertIn("What happened today", daily)
        self.assertEqual(radar, ["Follow the bill markup."])

    def test_live_modules_do_not_scrape_or_import_archived_summarizer(self):
        source = Path(summarize_stories.__file__).read_text(encoding="utf-8")
        self.assertNotIn("trafilatura", source)
        self.assertNotIn("fetch_html", source)
        self.assertNotIn("import archived_article_summarizer", source)
        self.assertNotIn("from archived_article_summarizer", source)
        self.assertNotIn("BeautifulSoup", source)

    def test_no_keys_raises_instead_of_writing_pending_copy(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(summarize_stories, "_post_json") as post_json:
                with self.assertRaises(summarize_stories.SummarizationError):
                    summarize_stories.summarize_macro(
                        [sample_story()], history=sample_history()
                    )
        post_json.assert_not_called()

    def test_one_gemini_call_receives_headlines_snippets_and_history(self):
        stories = [sample_story(), sample_story("Tariffs expand")]
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"},
        ):
            with patch.object(
                summarize_stories, "_post_json", return_value=gemini_body(sample_macro())
            ) as post_json:
                result = summarize_stories.summarize_macro(
                    stories, history=sample_history()
                )

        self.assertEqual(result.provider, "gemini")
        self.assertIn("daily_summary", result.macro_report)
        self.assertIn("tag_notes", result.macro_report)
        self.assertEqual(post_json.call_count, 1)
        prompt = post_json.call_args.args[1]["contents"][0]["parts"][0]["text"]
        self.assertIn("Oil prices jump", prompt)
        self.assertIn("tighter crude market", prompt)
        self.assertIn("Tariffs expand", prompt)
        self.assertIn("Chip export rules tighten", prompt)
        self.assertIn("Trade controls affect supply", prompt)
        self.assertIn("LAST 14 DAYS", prompt)
        self.assertIn("[Market Valuations]", prompt)
        self.assertIn("[Geopolitics & Trade]", prompt)
        self.assertNotIn("Article text:", prompt)
        self.assertNotIn("one call per story", prompt.lower())
        self.assertIn("generativelanguage.googleapis.com", post_json.call_args.args[0])
        self.assertIn("gemini-3.8-flash", post_json.call_args.args[0])
        self.assertEqual(post_json.call_args.args[2]["x-goog-api-key"], "gemini-test")
        self.assertNotIn("key=", post_json.call_args.args[0])
        self.assertEqual(
            post_json.call_args.args[1]["generationConfig"],
            {"maxOutputTokens": 4096, "thinkingConfig": {"thinkingLevel": "low"}},
        )

    def test_gemini_skips_thought_parts(self):
        gemini_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "internal reasoning"},
                            {"text": sample_macro()},
                        ]
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "_post_json", return_value=gemini_response):
                result = summarize_stories.summarize_macro(
                    [sample_story()], history=[]
                )

        self.assertEqual(result.provider, "gemini")
        self.assertIn("research_radar", result.macro_report)
        self.assertIn("Crude inventories.", result.macro_report)
        self.assertNotIn("internal reasoning", result.macro_report)

    def test_openai_is_used_when_gemini_key_is_absent(self):
        openai_body = {"choices": [{"message": {"content": sample_macro()}}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test"}, clear=True):
            with patch.object(
                summarize_stories, "_post_json", return_value=openai_body
            ) as post_json:
                result = summarize_stories.summarize_macro(
                    [sample_story()], history=sample_history()
                )

        self.assertEqual(result.provider, "openai")
        self.assertIn("daily_summary", result.macro_report)
        self.assertEqual(post_json.call_count, 1)
        self.assertEqual(post_json.call_args.args[0], summarize_stories.OPENAI_URL)
        self.assertEqual(post_json.call_args.args[1]["model"], "gpt-4o-mini")
        self.assertIn("tighter crude market", post_json.call_args.args[1]["messages"][1]["content"])

    def test_gemini_failure_falls_back_to_openai(self):
        openai_body = {"choices": [{"message": {"content": sample_macro()}}]}

        def fake_post(url, payload, headers, timeout=60):
            if "generativelanguage" in url:
                raise ValueError("Gemini unavailable")
            return openai_body

        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"},
        ):
            with patch.object(summarize_stories, "_post_json", side_effect=fake_post):
                result = summarize_stories.summarize_macro(
                    [sample_story()], history=[]
                )

        self.assertEqual(result.provider, "openai")
        self.assertIn("daily_summary", result.macro_report)

    def test_both_providers_failing_raises(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"},
        ):
            with patch.object(
                summarize_stories, "_post_json", side_effect=ValueError("down")
            ):
                with self.assertRaises(summarize_stories.SummarizationError):
                    summarize_stories.summarize_macro([sample_story()], history=[])

    def test_gemini_cascade_skips_429_then_uses_next_model(self):
        calls = []

        def fake_post(url, payload, headers, timeout=60):
            calls.append(url)
            if "gemini-3.8-flash" in url:
                raise urllib.error.HTTPError(url, 429, "quota", {}, None)
            if "gemini-3.7-flash" in url:
                return gemini_body(sample_macro())
            raise AssertionError(f"unexpected url {url}")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(summarize_stories, "_post_json", side_effect=fake_post):
                result = summarize_stories.summarize_macro(
                    [sample_story(), sample_story("Second headline")],
                    history=[],
                )

        self.assertEqual(result.provider, "gemini")
        self.assertIn("tag_notes", result.macro_report)
        self.assertEqual(len(calls), 2)
        self.assertIn("gemini-3.8-flash", calls[0])
        self.assertIn("gemini-3.7-flash", calls[1])

    def test_mock_path_never_posts_and_does_not_load_history_from_network(self):
        stories = [sample_story()]
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"},
        ):
            with patch.object(summarize_stories, "_post_json") as post_json:
                with patch.object(summarize_stories, "load_project_env") as load_env:
                    copied, provider, report = summarize_stories.summarize_stories(
                        stories, mock=True, history=[]
                    )
        post_json.assert_not_called()
        load_env.assert_not_called()
        self.assertEqual(provider, "mock")
        self.assertNotIn("macro_report", stories[0])
        self.assertEqual(copied[0]["headline"], "Oil prices jump")
        self.assertNotIn("ai_summary", copied[0])
        self.assertIn("tag_notes", report)
        self.assertIn("daily_summary", report)
        self.assertNotIn("AI Summary Pending", report)
        self.assertNotIn("Why It Matters", report)

    def test_save_creates_summarized_directory_and_macro_report(self):
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
                            selected_run, selected_path, mock=True, history=[]
                        )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(summarized_dir.is_dir())
            self.assertEqual(output_path, summarized_dir / "2026-10-04.json")
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["selected_run"], "2026-10-04.json")
            self.assertEqual(saved["summarizer"], "mock")
            self.assertNotIn("ai_headline", saved["stories"][0])
            self.assertNotIn("ai_summary", saved["stories"][0])
            self.assertIn("Market Valuations", saved["tag_notes"])
            self.assertIn("Oil prices jump", saved["daily_summary"])
            self.assertGreaterEqual(len(saved["research_radar"]), 3)
            self.assertIn("tag_notes", saved["macro_report"])
            self.assertNotIn("AI Summary Pending", saved["macro_report"])
            self.assertNotIn("Why It Matters", saved["macro_report"])
            self.assertEqual(saved["stories"][0]["headline"], "Oil prices jump")

    def test_summarize_stories_does_not_mutate_input(self):
        stories = [sample_story()]
        with patch.dict(os.environ, {}, clear=True):
            summarized, provider, report = summarize_stories.summarize_stories(
                stories, mock=True, history=[]
            )

        self.assertEqual(provider, "mock")
        self.assertNotIn("ai_summary", stories[0])
        self.assertNotIn("ai_headline", stories[0])
        self.assertIn("description", stories[0])
        self.assertEqual(summarized[0]["headline"], stories[0]["headline"])
        self.assertIsNot(summarized[0], stories[0])
        self.assertIn("research_radar", report)


if __name__ == "__main__":
    unittest.main()
