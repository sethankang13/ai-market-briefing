import io
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

        snapshot = {"fed_funds": {"status": "fetch failed"}}

        def market_step(mock=False):
            order.append("market")
            del mock
            return snapshot

        def attach_market(summarized_path, market):
            order.append(("market_attach", summarized_path, market is snapshot))
            return {"stories": [], "market_snapshot": market}

        def persist_step(summarized_run, market):
            order.append(("persist", market is snapshot))
            return Path("data/loop.db")

        with (
            patch.object(summarize_stories, "load_project_env", load_project_env),
            patch.object(run_briefing, "collect_step", collect_step),
            patch.object(run_briefing, "enrich_step", enrich_step),
            patch.object(run_briefing, "select_step", select_step),
            patch.object(run_briefing, "summarize_step", summarize_step),
            patch.object(run_briefing, "market_step", market_step),
            patch.object(run_briefing, "attach_market", attach_market),
            patch.object(run_briefing, "write_brief_step", write_brief_step),
            patch.object(run_briefing, "persist_step", persist_step),
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
                "market",
                ("summarize", Path("data/selected/2026-09-20.json"), False),
                ("market_attach", Path("data/summarized/2026-09-20.json"), True),
                ("write_brief", Path("data/summarized/2026-09-20.json")),
                ("persist", True),
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
            patch.object(run_briefing, "market_step", lambda: {"fed_funds": {}}),
            patch.object(run_briefing, "persist_step", lambda *args, **kwargs: Path("data/loop.db")),
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
                patch.object(run_briefing, "market_step", return_value={"fed_funds": {}}),
                patch.object(run_briefing, "attach_market", lambda path, snap: selected),
                patch.object(run_briefing, "persist_step", return_value=Path("data/loop.db")),
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
        self.assertNotIn("ai_headline", payload["stories"][0])
        self.assertNotIn("ai_summary", payload["stories"][0])
        self.assertIn("tag_notes", payload)
        self.assertIn("Legislation-&-Policy", payload["tag_notes"])
        self.assertIn("daily_summary", payload)
        self.assertIn("research_radar", payload)
        self.assertIn("tag_notes", payload["macro_report"])
        self.assertNotIn("AI Summary Pending", payload["macro_report"])
        self.assertNotIn("Why It Matters", payload["macro_report"])

    def test_completion_banner_includes_path_count_snapshot_and_failed_sources(self):
        selected = {
            "stories": [
                {"headline": "AI bill advances", "link": "https://example.com/ai-bill", "tags": []}
            ],
            "failed_sources": ["Politico AI Policy"],
            "market_snapshot": {
                "fed_funds": {"status": "ok", "rate": 4.33},
                "indexes": {
                    "^GSPC": {
                        "status": "ok",
                        "previous_close": 5123.45,
                        "percent_change": -0.42,
                    },
                    "^IXIC": {"status": "fetch failed", "error": "timeout"},
                    "^DJI": {
                        "status": "ok",
                        "previous_close": 42000.0,
                        "percent_change": 0.1,
                    },
                },
            },
        }
        snapshot = selected["market_snapshot"]
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(run_briefing, "collect_step", return_value=Path("raw.json")),
                patch.object(run_briefing, "enrich_step", return_value=Path("enriched.json")),
                patch.object(run_briefing, "select_step", return_value=Path("selected.json")),
                patch.object(
                    run_briefing, "write_brief_step", return_value=Path("briefs/2026-10-21.md")
                ),
                patch.object(run_briefing, "market_step", return_value=snapshot),
                patch.object(run_briefing, "attach_market", lambda path, snap: selected),
                patch.object(run_briefing, "persist_step", return_value=Path("data/loop.db")),
                patch.object(summarize_stories, "load_selected_run", return_value=selected),
                patch.object(summarize_stories, "load_project_env"),
                patch.object(
                    summarize_stories, "SUMMARIZED_DATA_DIRECTORY", Path(temp_dir)
                ),
                patch("sys.stdout", stdout),
            ):
                brief = run_briefing.run_briefing(mock=True)

        output = stdout.getvalue()
        self.assertEqual(brief, Path("briefs/2026-10-21.md"))
        self.assertIn("Loop complete", output)
        self.assertIn("Output: briefs/2026-10-21.md", output)
        self.assertIn("Stories selected: 1", output)
        self.assertIn("Market Snapshot:", output)
        self.assertIn("Fed Funds: 4.33%", output)
        self.assertIn("S&P 500: 5,123.45 (-0.42%)", output)
        self.assertNotIn("style=\"color:", output)
        self.assertIn("Nasdaq: fetch failed", output)
        self.assertIn("Dow: 42,000.00 (+0.10%)", output)
        self.assertIn("failed_sources: Politico AI Policy", output)
        self.assertNotIn("timeout", output)

    def test_open_flag_uses_mocked_subprocess_on_macos(self):
        selected = {"stories": [], "failed_sources": [], "market_snapshot": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(run_briefing, "collect_step", return_value=Path("raw.json")),
                patch.object(run_briefing, "enrich_step", return_value=Path("enriched.json")),
                patch.object(run_briefing, "select_step", return_value=Path("selected.json")),
                patch.object(
                    run_briefing, "write_brief_step", return_value=Path("briefs/2026-10-21.md")
                ),
                patch.object(run_briefing, "market_step", return_value={}),
                patch.object(run_briefing, "attach_market", lambda path, snap: selected),
                patch.object(run_briefing, "persist_step", return_value=Path("data/loop.db")),
                patch.object(summarize_stories, "load_selected_run", return_value=selected),
                patch.object(summarize_stories, "load_project_env"),
                patch.object(
                    summarize_stories, "SUMMARIZED_DATA_DIRECTORY", Path(temp_dir)
                ),
                patch.object(run_briefing.sys, "platform", "darwin"),
                patch.object(run_briefing.subprocess, "run") as subprocess_run,
            ):
                run_briefing.run_briefing(mock=True, open_after=True)

        subprocess_run.assert_called_once_with(
            ["open", "briefs/2026-10-21.md"], check=False
        )

    def test_open_is_a_noop_off_macos_and_does_not_call_subprocess(self):
        selected = {"stories": [], "failed_sources": [], "market_snapshot": {}}
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(run_briefing, "collect_step", return_value=Path("raw.json")),
                patch.object(run_briefing, "enrich_step", return_value=Path("enriched.json")),
                patch.object(run_briefing, "select_step", return_value=Path("selected.json")),
                patch.object(
                    run_briefing, "write_brief_step", return_value=Path("briefs/today.md")
                ),
                patch.object(run_briefing, "market_step", return_value={}),
                patch.object(run_briefing, "attach_market", lambda path, snap: selected),
                patch.object(run_briefing, "persist_step", return_value=Path("data/loop.db")),
                patch.object(summarize_stories, "load_selected_run", return_value=selected),
                patch.object(summarize_stories, "load_project_env"),
                patch.object(
                    summarize_stories, "SUMMARIZED_DATA_DIRECTORY", Path(temp_dir)
                ),
                patch.object(run_briefing.sys, "platform", "linux"),
                patch.object(run_briefing.subprocess, "run") as subprocess_run,
                patch("sys.stdout", stdout),
            ):
                run_briefing.run_briefing(mock=True, open_after=True)

        subprocess_run.assert_not_called()
        self.assertIn("--open is supported on macOS only", stdout.getvalue())

    def test_main_passes_open_and_mock_flags(self):
        with patch.object(run_briefing, "run_briefing") as run:
            run_briefing.main(["--mock", "--open"])
        run.assert_called_once_with(mock=True, open_after=True)

    def test_stories_for_loop_db_keeps_unselected_collected_rss(self):
        enriched = {
            "stories": [
                {
                    "headline": "Selected bill",
                    "link": "https://example.com/selected",
                    "source": "Wire",
                    "tags": ["Legislation-&-Policy"],
                },
                {
                    "headline": "Skipped item",
                    "link": "https://example.com/skipped",
                    "source": "Wire",
                    "tags": ["Foundation-Models"],
                },
            ]
        }
        summarized = {
            "selected_run": "2026-10-30.json",
            "stories": [
                {
                    "headline": "Selected bill",
                    "link": "https://example.com/selected",
                    "source": "Wire",
                    "ai_summary": "Why it matters.",
                    "tags": ["Legislation-&-Policy"],
                }
            ],
        }
        rows = run_briefing.stories_for_loop_db(summarized, enriched)
        by_url = {row["link"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_url["https://example.com/selected"]["is_selected"], 1)
        self.assertEqual(by_url["https://example.com/selected"]["ai_summary"], "Why it matters.")
        self.assertEqual(by_url["https://example.com/skipped"]["is_selected"], 0)

    def test_persist_step_reads_enriched_json_for_all_collected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            enriched_dir = root / "data" / "enriched"
            enriched_dir.mkdir(parents=True)
            (enriched_dir / "2026-10-30.json").write_text(
                json.dumps(
                    {
                        "stories": [
                            {
                                "headline": "Selected bill",
                                "link": "https://example.com/selected",
                                "source": "Wire",
                                "published_at": "2026-10-30",
                                "tags": ["Legislation-&-Policy"],
                            },
                            {
                                "headline": "Skipped item",
                                "link": "https://example.com/skipped",
                                "source": "Wire",
                                "published_at": "2026-10-30",
                                "tags": ["Foundation-Models"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db_path = root / "data" / "loop.db"
            summarized = {
                "selected_run": "2026-10-30.json",
                "macro_report": "{}",
                "stories": [
                    {
                        "headline": "Selected bill",
                        "link": "https://example.com/selected",
                        "source": "Wire",
                        "published_at": "2026-10-30",
                        "tags": ["Legislation-&-Policy"],
                    }
                ],
            }
            with (
                patch.object(run_briefing, "ENRICHED_DATA_DIRECTORY", enriched_dir),
                patch.object(run_briefing.db, "DEFAULT_DB_PATH", db_path),
            ):
                saved = run_briefing.persist_step(summarized, {"fed_funds": {}})
            rows = run_briefing.db.load_stories(db_path)

        self.assertEqual(saved, db_path)
        self.assertEqual(len(rows), 2)
        flags = {row["url"]: row["is_selected"] for row in rows}
        self.assertEqual(flags["https://example.com/selected"], 1)
        self.assertEqual(flags["https://example.com/skipped"], 0)


if __name__ == "__main__":
    unittest.main()
