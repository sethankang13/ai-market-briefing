import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import run_briefing
import summarize_stories


class RunBriefingTests(unittest.TestCase):
    def test_steps_run_in_order_and_pass_the_previous_file(self):
        order = []

        def load_project_env(env_path=None):
            order.append("load_env")

        def collect_step():
            order.append("collect")
            return Path("data/raw/2026-09-20.json")

        def enrich_step(raw_path):
            order.append(("enrich", raw_path))
            return Path("data/enriched/2026-09-20.json")

        def select_step(enriched_path):
            order.append(("select", enriched_path))
            return Path("data/selected/2026-09-20.json")

        def summarize_step(selected_path, mock=False):
            order.append(("summarize", selected_path, mock))
            return Path("data/summarized/2026-09-20.json")

        def write_brief_step(summarized_path):
            order.append(("write_brief", summarized_path))
            return Path("briefs/2026-09-20.md")

        with (
            patch.object(summarize_stories, "load_project_env", load_project_env),
            patch.object(run_briefing, "collect_step", collect_step),
            patch.object(run_briefing, "enrich_step", enrich_step),
            patch.object(run_briefing, "select_step", select_step),
            patch.object(run_briefing, "summarize_step", summarize_step),
            patch.object(run_briefing, "write_brief_step", write_brief_step),
        ):
            brief = run_briefing.run_briefing()

        self.assertEqual(brief, Path("briefs/2026-09-20.md"))
        self.assertEqual(
            order,
            [
                "load_env",
                "collect",
                ("enrich", Path("data/raw/2026-09-20.json")),
                ("select", Path("data/enriched/2026-09-20.json")),
                ("summarize", Path("data/selected/2026-09-20.json"), False),
                ("write_brief", Path("data/summarized/2026-09-20.json")),
            ],
        )

    def test_a_failed_step_stops_the_pipeline_and_names_the_step(self):
        called = []

        def collect_step():
            called.append("collect")
            return Path("data/raw/2026-09-20.json")

        def enrich_step(raw_path):
            called.append("enrich")
            raise RuntimeError("disk full")

        def select_step(enriched_path):
            called.append("select")
            return Path("data/selected/2026-09-20.json")

        with (
            patch.object(summarize_stories, "load_project_env"),
            patch.object(run_briefing, "collect_step", collect_step),
            patch.object(run_briefing, "enrich_step", enrich_step),
            patch.object(run_briefing, "select_step", select_step),
        ):
            with self.assertRaises(run_briefing.StepFailed) as caught:
                run_briefing.run_briefing()

        self.assertEqual(caught.exception.step, "enrich")
        self.assertIn("enrich failed", str(caught.exception))
        self.assertEqual(called, ["collect", "enrich"])

    def test_mock_does_not_call_gemini_or_openai(self):
        story = {
            "headline": "AI bill advances",
            "link": "https://example.com/ai-bill",
            "tags": ["Legislation-&-Policy"],
        }
        selected = {"stories": [story], "failed_sources": []}

        def boom(*args, **kwargs):
            raise AssertionError("model helper was called")

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(run_briefing, "collect_step", return_value=Path("raw.json")),
                patch.object(run_briefing, "enrich_step", return_value=Path("enriched.json")),
                patch.object(run_briefing, "select_step", return_value=Path("selected.json")),
                patch.object(
                    run_briefing, "write_brief_step", return_value=Path("briefs/today.md")
                ),
                patch.object(summarize_stories, "load_selected_run", return_value=selected),
                patch.object(summarize_stories, "load_project_env") as load_env,
                patch.object(
                    summarize_stories, "SUMMARIZED_DATA_DIRECTORY", Path(temp_dir)
                ),
                patch.object(summarize_stories, "summarize_with_gemini", side_effect=boom),
                patch.object(summarize_stories, "summarize_with_openai", side_effect=boom),
                patch.dict(
                    os.environ,
                    {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "openai-test"},
                ),
            ):
                brief = run_briefing.run_briefing(mock=True)
            load_env.assert_not_called()
            self.assertEqual(brief, Path("briefs/today.md"))
            saved = list(Path(temp_dir).glob("*.json"))
            self.assertEqual(len(saved), 1)
            payload = json.loads(saved[0].read_text(encoding="utf-8"))

        self.assertEqual(payload["summarizer"], "mock")
        self.assertEqual(
            payload["stories"][0]["ai_headline"],
            "[AI Headline Pending: AI bill advances]",
        )
        self.assertEqual(
            payload["stories"][0]["ai_summary"],
            "[AI Summary Pending: AI bill advances]",
        )


if __name__ == "__main__":
    unittest.main()
