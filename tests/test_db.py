import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import db
from write_the_loop import render_the_loop


class LoopDatabaseTests(unittest.TestCase):
    def test_append_run_stores_requested_columns(self):
        snapshot = {"fed_funds": {"status": "ok", "rate": 4.33}}
        stories = [
            {
                "published_at": "Tue, 06 Oct 2026 10:00:00 GMT",
                "headline": "Policy bill advances",
                "link": "https://example.com/bill",
                "source": "Example News",
                "full_text": "The full article body.",
                "ai_summary": "The bill can change compliance.",
                "tags": ["Legislation-&-Policy"],
            }
        ]
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loop.db"
            inserted = db.append_stories(stories, snapshot, db_path=path)
            inserted_again = db.append_stories(stories, snapshot, db_path=path)
            rows = db.load_stories(path)

        self.assertEqual(inserted, 1)
        self.assertEqual(inserted_again, 1)
        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual(
            set(row),
            {
                "id",
                "published_date",
                "headline",
                "url",
                "source",
                "full_text",
                "ai_summary",
                "tags",
                "market_snapshot_json",
            },
        )
        self.assertEqual(row["headline"], "Policy bill advances")
        self.assertEqual(row["url"], "https://example.com/bill")
        self.assertEqual(row["full_text"], "The full article body.")
        self.assertEqual(json.loads(row["tags"]), ["Legislation-&-Policy"])
        self.assertEqual(json.loads(row["market_snapshot_json"])["fed_funds"]["rate"], 4.33)

    def test_the_loop_report_uses_historical_title(self):
        report = render_the_loop(
            [
                {
                    "published_date": "2026-10-21",
                    "headline": "Policy bill advances",
                    "url": "https://example.com/bill",
                    "source": "Example News",
                    "tags": json.dumps(["Legislation-&-Policy"]),
                    "ai_summary": "The bill can change compliance.",
                }
            ]
        )
        self.assertTrue(report.startswith("# The Loop\n"))
        self.assertIn("[Policy bill advances](https://example.com/bill)", report)
        self.assertNotIn("# Looping...", report)
