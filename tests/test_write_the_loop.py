import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import write_the_loop


def sample_row(**overrides):
    row = {
        "id": 1,
        "published_date": "2026-10-20",
        "headline": "Policy bill advances",
        "url": "https://example.com/bill",
        "source": "Example News",
        "full_text": "",
        "ai_summary": "The bill can change compliance.",
        "tags": json.dumps(["US Politics"]),
        "market_snapshot_json": json.dumps(
            {
                "fetched_at": "2026-10-20T12:00:00+00:00",
                "fed_funds": {"status": "ok", "rate": 4.33},
                "indexes": {
                    "^GSPC": {
                        "status": "ok",
                        "previous_close": 5123.45,
                        "percent_change": -0.42,
                    },
                    "^IXIC": {"status": "fetch failed"},
                    "^DJI": {
                        "status": "ok",
                        "previous_close": 42000.0,
                        "percent_change": 0.1,
                    },
                },
            }
        ),
    }
    row.update(overrides)
    return row


class WriteTheLoopCliTests(unittest.TestCase):
    def test_parse_keeps_unhyphenated_tag_patterns(self):
        parsed = write_the_loop.parse_trajectory_report(
            json.dumps(
                {
                    "narrative_arcs": ["One arc"],
                    "signal_momentum": {"gaining": ["US Politics"], "fading": []},
                    "pivot_points": ["A pivot"],
                    "tag_patterns": {
                        "US Politics": "Policy holds.",
                        "Unknown": "drop me",
                        "Labor-Economy": "hyphen drop",
                    },
                }
            )
        )
        self.assertEqual(parsed["tag_patterns"], {"US Politics": "Policy holds."})
        markdown = write_the_loop.render_trajectory_markdown(parsed, 14)
        self.assertIn("## 🏛️ Tag-by-Tag Narrative Patterns", markdown)
        self.assertIn("### US Politics", markdown)
        self.assertIn("Policy holds.", markdown)
        self.assertNotIn("Unknown", markdown)
        self.assertNotIn("Labor-Economy", markdown)

    def test_argparse_converts_days_and_tag_types(self):
        args = write_the_loop.parse_arguments(
            ["--days", "14", "--tag", "US Politics", "--limit", "8"]
        )
        self.assertEqual(args.days, 14)
        self.assertIsInstance(args.days, int)
        self.assertEqual(args.tag, "US Politics")
        self.assertIsInstance(args.tag, str)
        self.assertEqual(args.limit, 8)
        self.assertFalse(args.open_after)
        self.assertFalse(args.synthesize)
        self.assertFalse(args.mock)
        self.assertEqual(args.out.name, "THE_LOOP.md")

    def test_argparse_defaults(self):
        args = write_the_loop.parse_arguments([])
        self.assertEqual(args.days, 14)
        self.assertIsNone(args.tag)
        self.assertEqual(args.limit, 15)
        self.assertFalse(args.open_after)
        self.assertFalse(args.synthesize)
        self.assertFalse(args.mock)

    def test_argparse_synthesize_and_mock(self):
        args = write_the_loop.parse_arguments(["--synthesize", "--mock", "--days", "14"])
        self.assertTrue(args.synthesize)
        self.assertTrue(args.mock)
        self.assertEqual(args.days, 14)

    def test_query_uses_parameterized_sqlite_and_never_concatenates_tag(self):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection.execute.return_value = cursor
        with patch.object(write_the_loop.sqlite3, "connect", return_value=connection) as connect:
            rows = write_the_loop.query_stories(
                days=14,
                tag="US Politics",
                limit=15,
                db_path=Path("/tmp/loop-test.db"),
            )
        self.assertEqual(rows, [])
        connect.assert_called_once()
        execute_calls = connection.execute.call_args_list
        query_call = execute_calls[-1]
        sql, params = query_call.args[0], query_call.args[1]
        self.assertIn("date('now', ?)", sql)
        self.assertIn("LIMIT ?", sql)
        self.assertNotIn("US Politics", sql)
        self.assertNotIn("-14 days", sql)
        self.assertEqual(params, ["-14 days", "%US Politics%", 15])

    def test_render_includes_glance_groups_and_honest_market_copy(self):
        duplicate = sample_row(
            id=2,
            headline="Policy bill advances",
            source="Second Desk",
            url="https://example.com/bill-2",
            market_snapshot_json=None,
        )
        report = write_the_loop.render_the_loop(
            [sample_row(), duplicate],
            days=14,
            tag="US Politics",
        )
        self.assertTrue(report.startswith("# The Loop: Macro Summary (Last 14 Days)\n"))
        self.assertIn("Filtered to tag `US Politics`.", report)
        self.assertIn("## At a Glance", report)
        self.assertIn("[Policy bill advances](https://example.com/bill)", report)
        self.assertIn("[Policy bill advances…](https://example.com/bill)", report)
        self.assertIn(
            'href="#us-politics">US Politics</a>: [Policy bill advances…]',
            report,
        )
        self.assertNotIn("### [#Legislation", report)
        self.assertIn("also covered by [Second Desk]", report)
        self.assertIn("## US Politics", report)
        self.assertNotIn("Why It Matters:", report)
        self.assertNotIn("*Tags:", report)
        self.assertIn("## Market Snapshot Trends", report)
        self.assertIn("Fed Funds 4.33%", report)
        self.assertNotIn("# Looping...", report)

    def test_missing_market_history_is_stated_not_invented(self):
        report = write_the_loop.render_the_loop(
            [sample_row(market_snapshot_json=None)],
            days=7,
        )
        self.assertIn("No stored market snapshot history for this window", report)
        self.assertNotIn("Fed Funds 4.33%", report)

    def test_open_flag_uses_mocked_subprocess_on_macos(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "THE_LOOP.md"
            with (
                patch.object(write_the_loop, "query_stories", return_value=[]),
                patch.object(write_the_loop.sys, "platform", "darwin"),
                patch.object(write_the_loop.subprocess, "run") as subprocess_run,
            ):
                write_the_loop.main(["--out", str(output), "--open"])
            subprocess_run.assert_called_once_with(["open", str(output)], check=False)
            self.assertTrue(output.exists())

    def test_open_is_a_noop_off_macos_and_does_not_call_subprocess(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "THE_LOOP.md"
            with (
                patch.object(write_the_loop, "query_stories", return_value=[]),
                patch.object(write_the_loop.sys, "platform", "linux"),
                patch.object(write_the_loop.subprocess, "run") as subprocess_run,
            ):
                write_the_loop.main(["--out", str(output), "--open"])
            subprocess_run.assert_not_called()

    def test_main_passes_cli_filters_to_save(self):
        with patch.object(write_the_loop, "save_the_loop", return_value=Path("out.md")) as save:
            write_the_loop.main(
                ["--days", "14", "--tag", "US Politics", "--limit", "4", "--out", "out.md"]
            )
        save.assert_called_once_with(
            output_path=Path("out.md"),
            days=14,
            tag="US Politics",
            limit=4,
            synthesize=False,
            mock=False,
        )

    def test_main_passes_synthesize_mock_days(self):
        with patch.object(write_the_loop, "save_the_loop", return_value=Path("out.md")) as save:
            write_the_loop.main(
                ["--synthesize", "--mock", "--days", "14", "--out", "out.md"]
            )
        save.assert_called_once_with(
            output_path=Path("out.md"),
            days=14,
            tag=None,
            limit=15,
            synthesize=True,
            mock=True,
        )

    def test_mock_synthesize_prepends_trajectory_without_gemini(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "THE_LOOP.md"
            missing_db = Path(temp_dir) / "loop.db"
            with (
                patch.object(write_the_loop.summarize_stories, "_post_json") as post_json,
                patch.object(write_the_loop.summarize_stories, "load_project_env") as load_env,
            ):
                write_the_loop.save_the_loop(
                    output_path=output,
                    db_path=missing_db,
                    days=14,
                    synthesize=True,
                    mock=True,
                )
            post_json.assert_not_called()
            load_env.assert_not_called()
            report = output.read_text(encoding="utf-8")
        self.assertTrue(report.startswith("# The Loop: Macro Summary (Last 14 Days)\n"))
        header_and_blank = "# The Loop: Macro Summary (Last 14 Days)\n\n"
        self.assertTrue(report.startswith(header_and_blank + "# Macro Trajectory (Last 14 Days)\n"))
        self.assertIn("## Narrative Arcs", report)
        self.assertIn("## Signal Momentum", report)
        self.assertIn("## Pivot Points", report)
        self.assertIn("## 🏛️ Tag-by-Tag Narrative Patterns", report)
        self.assertIn("### US Politics", report)
        self.assertIn("### Market Valuations", report)
        self.assertIn("### Labor & Economy", report)
        self.assertIn("### Geopolitics & Trade", report)
        self.assertIn("### Tech & Innovation", report)
        self.assertIn("### Venture & M&A", report)
        self.assertIn("Mock arc 1:", report)
        self.assertIn("Mock gaining: US Politics", report)
        self.assertIn("Mock fading: Venture & M&A", report)
        self.assertIn("Mock pivot:", report)
        self.assertIn("Mock pattern: US Politics", report)
        self.assertNotIn("US-Politics", report)
        self.assertNotIn("Labor-Economy", report)
        self.assertLess(
            report.find("# Macro Trajectory (Last 14 Days)"),
            report.find("## At a Glance"),
        )
        self.assertIn("No stories stored for this window.", report)
        self.assertNotIn("AI Summary Pending", report)

    def test_empty_and_missing_db_records_skip_gemini(self):
        with TemporaryDirectory() as temp_dir:
            missing_db = Path(temp_dir) / "missing.db"
            empty_db = Path(temp_dir) / "empty.db"
            invalid_db = Path(temp_dir) / "invalid.db"
            output = Path(temp_dir) / "THE_LOOP.md"
            db_module = write_the_loop.db
            db_module.append_stories(
                [
                    {
                        "published_at": "2026-11-04",
                        "headline": "Empty copy",
                        "link": "https://example.com/empty",
                        "source": "Example News",
                        "tags": ["US Politics"],
                    }
                ],
                db_path=empty_db,
                macro_report=None,
            )
            db_module.append_stories(
                [
                    {
                        "published_at": "2026-11-04",
                        "headline": "Broken copy",
                        "link": "https://example.com/broken",
                        "source": "Example News",
                        "tags": ["US Politics"],
                    }
                ],
                db_path=invalid_db,
                macro_report="{not-json",
            )
            with patch.object(write_the_loop.summarize_stories, "_post_json") as post_json:
                for db_path in (missing_db, empty_db, invalid_db):
                    write_the_loop.save_the_loop(
                        output_path=output,
                        db_path=db_path,
                        days=14,
                        synthesize=True,
                        mock=False,
                    )
                    report = output.read_text(encoding="utf-8")
                    self.assertIn("# Macro Trajectory (Last 14 Days)", report)
                    self.assertIn(
                        "No stored daily summaries or tag notes for this window",
                        report,
                    )
                    self.assertTrue(
                        report.startswith("# The Loop: Macro Summary (Last 14 Days)\n")
                    )
                    self.assertIn("## At a Glance", report)
            post_json.assert_not_called()

    def test_live_synthesize_sends_one_gemini_call_with_summaries_and_notes(self):
        payload = json.dumps(
            {
                "narrative_arcs": [
                    "Policy and markets stay linked.",
                    "Labor remains the second thread.",
                    "Trade keeps a multi-week arc.",
                ],
                "signal_momentum": {
                    "gaining": ["US Politics"],
                    "fading": ["Venture & M&A"],
                },
                "pivot_points": ["A rate-path reversal."],
                "tag_patterns": {
                    "US Politics": "Policy notes stay the stored through-line."
                },
            }
        )
        gemini_response = {
            "candidates": [{"content": {"parts": [{"text": payload}]}}]
        }
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "loop.db"
            output = Path(temp_dir) / "THE_LOOP.md"
            write_the_loop.db.append_stories(
                [
                    {
                        "published_at": "2026-11-04",
                        "headline": "Policy bill advances",
                        "link": "https://example.com/bill",
                        "source": "Example News",
                        "tags": ["US Politics"],
                    }
                ],
                db_path=db_path,
                macro_report=json.dumps(
                    {
                        "tag_notes": {"US Politics": "The bill remains the week's core."},
                        "daily_summary": "Policy headlines dominated the window.",
                        "research_radar": ["Follow the markup."],
                    }
                ),
            )
            with patch.dict(
                write_the_loop.os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True
            ):
                with patch.object(
                    write_the_loop.summarize_stories,
                    "_post_json",
                    return_value=gemini_response,
                ) as post_json:
                    write_the_loop.save_the_loop(
                        output_path=output,
                        db_path=db_path,
                        days=14,
                        synthesize=True,
                        mock=False,
                    )
            prompt = post_json.call_args.args[1]["contents"][0]["parts"][0]["text"]
            report = output.read_text(encoding="utf-8")
        post_json.assert_called_once()
        self.assertIn("gemini-3.8-flash", post_json.call_args.args[0])
        self.assertIn("Policy headlines dominated the window.", prompt)
        self.assertIn("The bill remains the week's core.", prompt)
        self.assertIn("narrative_arcs", prompt)
        self.assertIn("tag_patterns", prompt)
        self.assertIn("US Politics", prompt)
        self.assertIn("Market Valuations", prompt)
        self.assertIn("Labor & Economy", prompt)
        self.assertIn("Geopolitics & Trade", prompt)
        self.assertIn("Tech & Innovation", prompt)
        self.assertIn("Venture & M&A", prompt)
        self.assertNotIn("At a Glance", write_the_loop.TRAJECTORY_SYSTEM_PROMPT)
        self.assertTrue(report.startswith("# The Loop: Macro Summary (Last 14 Days)\n"))
        self.assertIn("# Macro Trajectory (Last 14 Days)", report)
        self.assertIn("## 🏛️ Tag-by-Tag Narrative Patterns", report)
        self.assertIn("Policy notes stay the stored through-line.", report)
        self.assertIn("Policy and markets stay linked.", report)
        self.assertIn("US Politics", report)
        self.assertIn("A rate-path reversal.", report)
        self.assertLess(
            report.find("# Macro Trajectory (Last 14 Days)"),
            report.find("[Policy bill advances]"),
        )


if __name__ == "__main__":
    unittest.main()
