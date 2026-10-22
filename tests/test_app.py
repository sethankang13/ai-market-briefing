import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _passthrough_cache(func=None, **_kwargs):
    """Stand in for st.cache_data / st.cache_resource without a Streamlit server."""
    if func is not None:
        return func

    def decorator(wrapped):
        return wrapped

    return decorator


def _install_streamlit_stub():
    stub = MagicMock()
    stub.cache_data = _passthrough_cache
    stub.cache_resource = _passthrough_cache
    sys.modules["streamlit"] = stub
    return stub


class AppImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_streamlit_stub()
        import app as app_module

        cls.app = app_module

    def test_app_module_imports_without_starting_a_server(self):
        self.assertTrue(hasattr(self.app, "main"))
        self.assertTrue(callable(self.app.main))
        self.assertTrue(hasattr(self.app, "search_stories"))

    def test_list_briefing_dates_newest_first_and_skips_other_names(self):
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "2026-10-04.md").write_text("# older\n", encoding="utf-8")
            (folder / "2026-10-15.md").write_text("# newer\n", encoding="utf-8")
            (folder / "THE_LOOP.md").write_text("# archive\n", encoding="utf-8")
            (folder / "notes.txt").write_text("ignore\n", encoding="utf-8")
            dates = self.app.list_briefing_dates(folder)
            latest = self.app.latest_briefing_date(folder)
        self.assertEqual(dates, ["2026-10-15", "2026-10-04"])
        self.assertEqual(latest, "2026-10-15")

    def test_missing_briefs_directory_is_empty(self):
        missing = Path("/tmp/loop-briefs-missing-dir-does-not-exist")
        self.assertEqual(self.app.list_briefing_dates(missing), [])
        self.assertIsNone(self.app.latest_briefing_date(missing))

    def test_search_stories_uses_bound_parameters_and_filters(self):
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
            connection.executemany(
                "INSERT INTO stories (published_date, headline, source, ai_summary, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        "2026-10-15",
                        "Policy bill advances",
                        "Example News",
                        "The bill can change compliance.",
                        '["Legislation-&-Policy"]',
                    ),
                    (
                        "2026-10-14",
                        "Chip export rules tighten",
                        "Other Source",
                        "Trade controls affect supply.",
                        '["Geopolitics-&-Trade"]',
                    ),
                ],
            )
            connection.commit()
            connection.close()

            by_tag = self.app.search_stories(
                str(path), "Legislation-&-Policy", "", ""
            )
            by_source = self.app.search_stories(str(path), "", "Other Source", "")
            by_query = self.app.search_stories(str(path), "", "", "compliance")
            missing_db = self.app.search_stories(
                str(Path(temp_dir) / "nope.db"), "", "", "anything"
            )
            article_count = self.app.count_stored_articles(str(path))
            missing_count = self.app.count_stored_articles(
                str(Path(temp_dir) / "nope.db")
            )
            sources = self.app.unique_sources(str(path))

        self.assertEqual(len(by_tag), 1)
        self.assertEqual(by_tag[0]["headline"], "Policy bill advances")
        self.assertEqual(by_tag[0]["tags"], ["Legislation-&-Policy"])
        self.assertEqual(len(by_source), 1)
        self.assertEqual(by_source[0]["source"], "Other Source")
        self.assertEqual(len(by_query), 1)
        self.assertIn("compliance", by_query[0]["ai_summary"])
        self.assertEqual(missing_db, [])
        self.assertEqual(article_count, 2)
        self.assertEqual(missing_count, 0)
        self.assertEqual(sources, ["Example News", "Other Source"])

    def test_search_sql_keeps_placeholders_instead_of_interpolating(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertIn("AND tags LIKE ?", source)
        self.assertIn("AND source = ?", source)
        self.assertIn("AND (headline LIKE ? OR ai_summary LIKE ?)", source)
        self.assertNotIn("AND tags LIKE '%", source)
        self.assertNotIn(f"LIKE '%{{", source)
