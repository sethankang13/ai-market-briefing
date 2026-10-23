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
                "INSERT INTO stories (published_date, headline, url, source, ai_summary, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        "2026-10-15",
                        "Policy bill advances",
                        "https://example.com/bill",
                        "Example News",
                        "The bill can change compliance.",
                        '["Legislation-&-Policy"]',
                    ),
                    (
                        "2026-10-14",
                        "Chip export rules tighten",
                        "https://example.com/chips",
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
        self.assertEqual(by_tag[0]["url"], "https://example.com/bill")
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
        self.assertIn("SELECT published_date, headline, url, source, tags, ai_summary", source)
        self.assertIn("def stories_for_tag", source)

    def test_tag_query_param_and_date_grouped_archive_helpers(self):
        self.assertEqual(
            self.app.read_query_tag({"tag": "Legislation-&-Policy"}),
            "Legislation-&-Policy",
        )
        self.assertEqual(
            self.app.read_query_tag({"tag": ["Foundation-Models"]}),
            "Foundation-Models",
        )
        self.assertIsNone(self.app.read_query_tag({}))
        rows = [
            {
                "published_date": "2026-10-15",
                "headline": "Newer bill",
                "url": "https://example.com/new",
                "source": "Example News",
                "tags": ["Legislation-&-Policy"],
                "ai_summary": "",
            },
            {
                "published_date": "2026-10-15",
                "headline": "Same-day bill",
                "url": "https://example.com/same",
                "source": "Other Source",
                "tags": ["Legislation-&-Policy"],
                "ai_summary": "",
            },
            {
                "published_date": "2026-10-14",
                "headline": "Older bill",
                "url": "https://example.com/old",
                "source": "Example News",
                "tags": ["Legislation-&-Policy"],
                "ai_summary": "",
            },
        ]
        grouped = self.app.group_stories_by_date(rows)
        self.assertEqual([date for date, _rows in grouped], ["2026-10-15", "2026-10-14"])
        self.assertEqual(len(grouped[0][1]), 2)
        chips = self.app.tag_chips_html(["Legislation-&-Policy", "Foundation-Models"])
        self.assertIn("http://127.0.0.1:8501/?tag=Legislation-%26-Policy", chips)
        self.assertIn("#Foundation-Models", chips)

    def test_stories_for_tag_uses_parameterized_like(self):
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
                "INSERT INTO stories (published_date, headline, url, source, ai_summary, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        "2026-10-15",
                        "Policy bill advances",
                        "https://example.com/bill",
                        "Example News",
                        "",
                        '["Legislation-&-Policy"]',
                    ),
                    (
                        "2026-10-14",
                        "Chip export rules tighten",
                        "https://example.com/chips",
                        "Other Source",
                        "",
                        '["Geopolitics-&-Trade"]',
                    ),
                    (
                        "2026-10-13",
                        "Older policy note",
                        "https://example.com/older",
                        "Example News",
                        "",
                        '["Legislation-&-Policy"]',
                    ),
                ],
            )
            connection.commit()
            connection.close()
            rows = self.app.stories_for_tag(str(path), "Legislation-&-Policy")

        self.assertEqual(
            [row["headline"] for row in rows],
            ["Policy bill advances", "Older policy note"],
        )
        dates = [date for date, _rows in self.app.group_stories_by_date(rows)]
        self.assertEqual(dates, ["2026-10-15", "2026-10-13"])


class HeadlineAndPopoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_streamlit_stub()
        import app as app_module

        cls.app = app_module

    def test_headline_markdown_links_or_bolds_without_raw_urls(self):
        linked = self.app.headline_markdown(
            "Policy bill advances", "https://example.com/bill"
        )
        missing = self.app.headline_markdown("Policy bill advances", "")
        untitled = self.app.headline_markdown("", None)
        self.assertEqual(linked, "### [Policy bill advances](https://example.com/bill)")
        self.assertEqual(missing, "### **Policy bill advances**")
        self.assertEqual(untitled, "### **(untitled)**")
        self.assertFalse(missing.startswith("### https://"))
        html_linked = self.app.headline_html(
            "Policy bill advances", "https://example.com/bill"
        )
        self.assertIn('target="_blank"', html_linked)
        self.assertIn("Policy bill advances", html_linked)
        self.assertNotIn(">https://example.com/bill<", html_linked)

    def test_group_stories_by_normalized_headline_for_popover(self):
        rows = [
            {
                "published_date": "2026-10-15",
                "headline": "Rates rise",
                "url": "https://example.com/reuters",
                "source": "Reuters",
                "tags": ["Market-Valuations"],
                "ai_summary": "Primary copy.",
            },
            {
                "published_date": "2026-10-15",
                "headline": "  RATES   rise ",
                "url": "https://example.com/cnbc",
                "source": "CNBC",
                "tags": ["Market-Valuations"],
                "ai_summary": "Duplicate copy.",
            },
            {
                "published_date": "2026-10-15",
                "headline": "Rates rise",
                "url": "https://example.com/reuters",
                "source": "Reuters",
                "tags": ["Market-Valuations"],
                "ai_summary": "Same source again.",
            },
            {
                "published_date": "2026-10-14",
                "headline": "Other story",
                "url": "",
                "source": "AP",
                "tags": [],
                "ai_summary": "Solo.",
            },
        ]
        groups = self.app.group_stories_by_headline(rows)
        self.assertEqual(len(groups), 2)
        clustered = groups[0]
        self.assertEqual(clustered["headline"], "Rates rise")
        self.assertEqual(len(clustered["sources"]), 2)
        self.assertEqual(
            clustered["sources"][0],
            {
                "source": "Reuters",
                "headline": "Rates rise",
                "url": "https://example.com/reuters",
            },
        )
        self.assertEqual(clustered["sources"][1]["source"], "CNBC")
        self.assertEqual(
            self.app.source_bullet_markdown(
                "CNBC", "Rates rise", "https://example.com/cnbc"
            ),
            "- [CNBC: Rates rise](https://example.com/cnbc)",
        )
        self.assertEqual(len(groups[1]["sources"]), 1)

    def test_display_brief_rewrites_glance_slugs_and_drops_bare_urls(self):
        markdown = (
            "## At a Glance\n"
            "\n"
            "- [Rates rise](#rates-rise)\n"
            "\n"
            "## Market-Valuations\n"
            "\n"
            '<a id="rates-rise"></a>\n'
            "- [Rates rise](https://example.com/rates)\n"
            "  also covered by [CNBC]\n"
            "https://example.com/should-not-print\n"
        )
        displayed = self.app.display_brief_markdown(markdown)
        self.assertIn("- [Rates rise](https://example.com/rates)", displayed)
        self.assertNotIn("](#rates-rise)", displayed)
        self.assertNotIn("https://example.com/should-not-print", displayed)
        self.assertIn("also covered by [CNBC]", displayed)
