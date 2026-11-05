import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
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
                "tags": ["US Politics"],
            }
        ]
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loop.db"
            inserted = db.append_stories(stories, snapshot, db_path=path)
            inserted_again = db.append_stories(stories, snapshot, db_path=path)
            rows = db.load_stories(path)

        self.assertEqual(inserted, 1)
        self.assertEqual(inserted_again, 0)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            set(row),
            {
                "id",
                "published_date",
                "headline",
                "url",
                "source",
                "sub_feed",
                "full_text",
                "ai_summary",
                "tags",
                "market_snapshot_json",
                "macro_report",
                "is_selected",
            },
        )
        self.assertEqual(row["is_selected"], 1)
        self.assertEqual(row["headline"], "Policy bill advances")
        self.assertEqual(row["url"], "https://example.com/bill")
        self.assertEqual(row["sub_feed"], "Example News")
        self.assertEqual(row["published_date"], "2026-10-06")
        self.assertEqual(row["full_text"], "The full article body.")
        self.assertEqual(json.loads(row["tags"]), ["US Politics"])
        self.assertEqual(json.loads(row["market_snapshot_json"])["fed_funds"]["rate"], 4.33)
        self.assertIsNone(row["macro_report"])

    def test_the_loop_report_uses_historical_title(self):
        report = render_the_loop(
            [
                {
                    "published_date": "2026-10-21",
                    "headline": "Policy bill advances",
                    "url": "https://example.com/bill",
                    "source": "Example News",
                    "tags": json.dumps(["US Politics"]),
                    "ai_summary": "The bill can change compliance.",
                }
            ]
        )
        self.assertTrue(report.startswith("# The Loop: Macro Summary (Last 7 Days)\n"))
        self.assertIn("[Policy bill advances](https://example.com/bill)", report)
        self.assertIn("## At a Glance", report)
        self.assertNotIn("# Looping...", report)

    def test_load_recent_stories_uses_parameterized_fourteen_day_sql(self):
        source = Path(db.__file__).read_text(encoding="utf-8")
        self.assertIn("WHERE published_date >= date('now', '-14 days')", source)
        self.assertEqual(
            db.RECENT_STORIES_SQL.count("date('now', '-14 days')"),
            1,
        )
        snapshot = {"fed_funds": {"status": "ok", "rate": 4.33}}
        today = datetime.now(timezone.utc).date()
        recent_day = (today - timedelta(days=1)).isoformat()
        old_day = (today - timedelta(days=40)).isoformat()
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loop.db"
            db.append_stories(
                [
                    {
                        "published_at": recent_day,
                        "headline": "Recent bill",
                        "link": "https://example.com/recent",
                        "source": "Example News",
                        "description": "Snippet only.",
                        "tags": ["US Politics"],
                    }
                ],
                snapshot,
                db_path=path,
                macro_report="# The Loop: Macro Landscape\n",
            )
            db.append_stories(
                [
                    {
                        "published_at": old_day,
                        "headline": "Old bill",
                        "link": "https://example.com/old",
                        "source": "Example News",
                        "tags": ["US Politics"],
                    }
                ],
                snapshot,
                db_path=path,
            )
            recent = db.load_recent_stories(path)
        headlines = [row["headline"] for row in recent]
        self.assertIn("Recent bill", headlines)
        self.assertNotIn("Old bill", headlines)
        self.assertEqual(recent[0]["full_text"], "Snippet only.")
        self.assertIn("# The Loop: Macro Landscape", recent[0]["macro_report"] or "")

    def test_append_stores_unselected_rss_and_replaces_same_day_url(self):
        snapshot = {"fed_funds": {"status": "ok", "rate": 4.33}}
        collected = [
            {
                "published_at": "2026-10-30",
                "headline": "Policy bill advances",
                "link": "https://example.com/bill",
                "source": "Example News",
                "tags": ["US Politics"],
                "is_selected": 1,
            },
            {
                "published_at": "2026-10-30",
                "headline": "Other RSS item",
                "link": "https://example.com/other",
                "source": "Wire",
                "tags": ["Tech & Innovation"],
                "is_selected": 0,
            },
        ]
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loop.db"
            first = db.append_stories(collected, snapshot, db_path=path)
            updated = [
                {
                    **collected[0],
                    "headline": "Policy bill advances (updated)",
                    "is_selected": 1,
                },
                collected[1],
            ]
            second = db.append_stories(updated, snapshot, db_path=path)
            rows = db.load_stories(path)
            by_url = {row["url"]: row for row in rows}

        self.assertEqual(first, 2)
        self.assertEqual(second, 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_url["https://example.com/bill"]["headline"], "Policy bill advances (updated)")
        self.assertEqual(by_url["https://example.com/bill"]["is_selected"], 1)
        self.assertEqual(by_url["https://example.com/other"]["is_selected"], 0)

    def test_ensure_schema_dedupes_same_day_urls_for_unique_index(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loop.db"
            connection = sqlite3.connect(path)
            connection.execute(db.SCHEMA)
            connection.execute(
                "INSERT INTO stories (published_date, headline, url, source) "
                "VALUES (?, ?, ?, ?)",
                ("2026-11-04", "First", "https://example.com/dup", "Wire"),
            )
            connection.execute(
                "INSERT INTO stories (published_date, headline, url, source) "
                "VALUES (?, ?, ?, ?)",
                ("2026-11-04", "Second", "https://example.com/dup", "Wire"),
            )
            connection.commit()
            connection.close()
            rows = db.load_stories(path)
            headlines = [row["headline"] for row in rows]
        self.assertEqual(len(rows), 1)
        self.assertEqual(headlines, ["Second"])

    def test_existing_database_migrates_is_selected_column(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loop.db"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    published_date TEXT,
                    headline TEXT,
                    url TEXT,
                    source TEXT,
                    full_text TEXT,
                    ai_summary TEXT,
                    tags TEXT,
                    market_snapshot_json TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO stories (published_date, headline, url, source) "
                "VALUES (?, ?, ?, ?)",
                ("2026-10-15", "Old pick", "https://example.com/old", "Wire"),
            )
            connection.commit()
            connection.close()
            rows = db.load_stories(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["is_selected"], 1)
        self.assertEqual(rows[0]["headline"], "Old pick")
