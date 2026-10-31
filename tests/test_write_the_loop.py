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
        self.assertEqual(args.out.name, "THE_LOOP.md")

    def test_argparse_defaults(self):
        args = write_the_loop.parse_arguments([])
        self.assertEqual(args.days, 7)
        self.assertIsNone(args.tag)
        self.assertEqual(args.limit, 15)
        self.assertFalse(args.open_after)

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
            'href="#us-politics">US Politics</a>:',
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
        )


if __name__ == "__main__":
    unittest.main()
