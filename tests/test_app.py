import os
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
                        '["US Politics"]',
                    ),
                    (
                        "2026-10-14",
                        "Chip export rules tighten",
                        "https://example.com/chips",
                        "Other Source",
                        "Trade controls affect supply.",
                        '["Geopolitics & Trade"]',
                    ),
                ],
            )
            connection.commit()
            connection.close()

            by_tag = self.app.search_stories(
                str(path), "US Politics", "", ""
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
        self.assertEqual(by_tag[0]["tags"], ["US Politics"])
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
            self.app.read_query_tag({"tag": "US Politics"}),
            "US Politics",
        )
        self.assertEqual(
            self.app.read_query_tag({"tag": ["Tech & Innovation"]}),
            "Tech & Innovation",
        )
        self.assertIsNone(self.app.read_query_tag({}))
        rows = [
            {
                "published_date": "2026-10-15",
                "headline": "Newer bill",
                "url": "https://example.com/new",
                "source": "Example News",
                "tags": ["US Politics"],
                "ai_summary": "",
            },
            {
                "published_date": "2026-10-15",
                "headline": "Same-day bill",
                "url": "https://example.com/same",
                "source": "Other Source",
                "tags": ["US Politics"],
                "ai_summary": "",
            },
            {
                "published_date": "2026-10-14",
                "headline": "Older bill",
                "url": "https://example.com/old",
                "source": "Example News",
                "tags": ["US Politics"],
                "ai_summary": "",
            },
        ]
        grouped = self.app.group_stories_by_date(rows)
        self.assertEqual([date for date, _rows in grouped], ["2026-10-15", "2026-10-14"])
        self.assertEqual(len(grouped[0][1]), 2)
        chips = self.app.tag_chips_html(["US Politics", "Tech & Innovation"])
        self.assertIn("http://127.0.0.1:8501/?tag=US+Politics", chips)
        self.assertIn("#Tech &amp; Innovation", chips)
        self.assertNotIn("#Tech & Innovation", chips)

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
                        '["US Politics"]',
                    ),
                    (
                        "2026-10-14",
                        "Chip export rules tighten",
                        "https://example.com/chips",
                        "Other Source",
                        "",
                        '["Geopolitics & Trade"]',
                    ),
                    (
                        "2026-10-13",
                        "Older policy note",
                        "https://example.com/older",
                        "Example News",
                        "",
                        '["US Politics"]',
                    ),
                ],
            )
            connection.commit()
            connection.close()
            rows = self.app.stories_for_tag(str(path), "US Politics")

        self.assertEqual(
            [row["headline"] for row in rows],
            ["Policy bill advances", "Older policy note"],
        )
        dates = [date for date, _rows in self.app.group_stories_by_date(rows)]
        self.assertEqual(dates, ["2026-10-15", "2026-10-13"])

    def test_humanize_tag_unhyphenates_user_facing_labels(self):
        self.assertEqual(self.app.humanize_tag("US Politics"), "US Politics")
        self.assertEqual(self.app.humanize_tag("Market-Valuations"), "Market Valuations")
        self.assertEqual(self.app.humanize_tag("Legislation-&-Policy"), "Legislation & Policy")
        self.assertEqual(self.app.humanize_tag("Tech & Innovation"), "Tech & Innovation")
        displayed = self.app.humanize_brief_markdown(
            "# Looping... (2026-10-24)\n\n"
            "Loop: AI Market Briefing. Selected public reporting, organized by topic. "
            "Links lead to the original source.\n\n"
            "## US Politics\n\n## Legislation-&-Policy\n\n## Daily Summary\n"
        )
        self.assertNotIn("Looping...", displayed)
        self.assertNotIn("Selected public reporting", displayed)
        self.assertIn("## US Politics", displayed)
        self.assertIn("## Legislation & Policy", displayed)
        self.assertIn("## Daily Summary & Research Topics", displayed)

    def test_display_rewrites_research_topics_into_ask_gemini_links(self):
        displayed = self.app.display_brief_markdown(
            "# Looping... (2026-10-23)\n\n"
            "## Daily Summary & Research Topics\n\n"
            "Policy cluster from RSS headlines.\n\n"
            "Research topics to look into more\n\n"
            "1. Follow the bill markup.\n"
            "2. Model evals\n"
        )
        self.assertIn("**Ask Gemini:**", displayed)
        self.assertNotIn("Research topics to look into more", displayed)
        self.assertIn("https://www.google.com/search?udm=50&amp;q=", displayed)
        self.assertNotIn("gemini.google.com/app?q=", displayed)
        self.assertIn("Follow the bill markup", displayed)
        self.assertIn("Model evals", displayed)
        self.assertIn("target=\"_blank\"", displayed)

    def test_display_upgrades_old_gemini_app_query_links(self):
        displayed = self.app.display_brief_markdown(
            "# Looping... (2026-10-23)\n\n"
            "## Daily Summary & Research Topics\n\n"
            "Policy cluster from RSS headlines.\n\n"
            "**Ask Gemini:**\n\n"
            '1. <a href="https://gemini.google.com/app?q=old" target="_blank" rel="noopener noreferrer">Follow the bill markup</a>\n'
        )
        self.assertIn("https://www.google.com/search?udm=50&amp;q=", displayed)
        self.assertNotIn("gemini.google.com/app?q=", displayed)
        self.assertIn("Follow the bill markup", displayed)
        self.assertIn("Executive%20summary", displayed)

    def test_display_splits_glance_clusters_and_rewrites_snapshot_deltas(self):
        displayed = self.app.display_brief_markdown(
            "# Looping... (2026-10-23)\n\n"
            "## Market Snapshot\n\n"
            '- S&P 500: 5,123.45 (<span style="color:#2F7D4F">+0.35%</span>)\n'
            '- Dow: 42,000.00 (<span style="color:#C04545">-0.45%</span>)\n\n'
            "## At a Glance\n\n"
            '<a class="loop-glance" href="#us-politics">US Politics</a>: '
            "[Apple may try…](https://example.com/a), "
            "[States take steps…](https://example.com/b)\n\n"
            "---\n"
        )
        self.assertIn('class="loop-delta loop-delta-up"', displayed)
        self.assertIn('class="loop-delta loop-delta-down"', displayed)
        self.assertNotIn("#2F7D4F", displayed)
        self.assertNotIn("#C04545", displayed)
        self.assertIn(
            '- <a class="loop-glance" href="#us-politics">US Politics</a> [Apple may try…](https://example.com/a)',
            displayed,
        )
        self.assertIn(
            '- <a class="loop-glance" href="#us-politics">US Politics</a> [States take steps…](https://example.com/b)',
            displayed,
        )
        self.assertNotIn("</a>: [Apple may try…]", displayed)

    def test_static_svgs_are_utf8_and_bad_assets_are_skipped(self):
        static = Path(self.app.__file__).resolve().parents[1] / "static"
        for name in (
            "loop-logo.svg",
            "loop-banner.svg",
            "loop-glasses.svg",
            "loop-glasses-light.svg",
            "loop-glasses-dark.svg",
        ):
            path = static / name
            self.assertTrue(path.is_file(), name)
            raw = path.read_bytes()
            raw.decode("utf-8")
            self.assertNotIn(b"\xb7", raw)
            self.assertTrue(self.app.static_asset_is_utf8(path))
        for name in ("loop-icon-light.png", "loop-icon-dark.png", "loop-glasses.png"):
            self.assertTrue((static / name).is_file(), name)
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertIn("LOOP: AI Market Briefing", source)
        self.assertIn("family=Inter", self.app.brand_css())
        self.assertIn("--loop-navy: #263B60", source)
        self.assertIn("scroll-margin-top: 90px", source)
        self.assertIn('stroke="currentColor"', self.app.LOOP_HEADER_HTML)
        self.assertIn("loop-header", self.app.LOOP_HEADER_HTML)
        css = self.app.brand_css()
        script = self.app.brand_theme_script()
        config = Path(self.app.__file__).resolve().parents[1] / ".streamlit" / "config.toml"
        toml = config.read_text(encoding="utf-8")
        self.assertEqual(self.app.LOOP_VERSION, "4.1.2")
        version_file = Path(self.app.__file__).resolve().parents[1] / "VERSION"
        self.assertEqual(version_file.read_text(encoding="utf-8").strip(), "4.1.2")
        self.assertIn('data-loop-theme="light"', css)
        self.assertIn('data-loop-theme="dark"', css)
        self.assertNotIn('data-loop-theme="system"', css)
        self.assertNotIn("loop-appearance", self.app.LOOP_HEADER_HTML)
        self.assertNotIn("loop-theme-toggle", self.app.LOOP_HEADER_HTML)
        self.assertNotIn("data-loop-theme-set", self.app.LOOP_HEADER_HTML)
        self.assertNotIn("data-loop-theme-set", script)
        self.assertIn("stActiveTheme-", script)
        self.assertIn("stMainMenuItem-theme-", script)
        self.assertIn('JSON.stringify(label)', script)
        self.assertIn('html.setAttribute("data-theme", theme)', script)
        self.assertIn("addEventListener(\"storage\"", script)
        self.assertIn("html:not([data-loop-theme])", css)
        self.assertIn("--loop-fg: #F7F6F2", css)
        self.assertIn("--loop-fg: #171C25", css)
        self.assertIn("--loop-page: #171C25", css)
        self.assertIn("--loop-page: #F7F6F2", css)
        self.assertIn("--loop-input: #E5EAF0", css)
        self.assertIn("--loop-input: #171C25", css)
        self.assertIn("color: var(--loop-fg)", css)
        self.assertNotIn("var(--loop-fg, inherit)", css)
        self.assertNotIn("color:#fff", css.replace(" ", "").lower())
        self.assertNotIn("#ffffff", css.lower())
        self.assertIn("background-color: #F7F6F2 !important", css)
        self.assertIn("background-color: #171C25 !important", css)
        self.assertIn("background-color: var(--loop-input) !important", css)
        self.assertIn(".react-aria-ComboBox", css)
        self.assertIn('html[data-loop-theme="light"] .stApp', css)
        self.assertIn('html[data-loop-theme="dark"] .stApp', css)
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn("@media (prefers-color-scheme: light)", css)
        self.assertIn("border-radius: 10px", css)
        self.assertNotIn("style.colorScheme", script)
        self.assertIn("[data-testid=\"stTabs\"]", css)
        self.assertIn("[data-testid=\"stSelectbox\"]", css)
        self.assertIn("[data-testid=\"stForm\"]", css)
        self.assertIn("[data-testid=\"stExpander\"]", css)
        self.assertIn("a.loop-glance", css)
        self.assertIn('a[href^="#"]', css)
        self.assertIn("flex-direction: row", css)
        self.assertIn("justify-content: flex-start", css)
        self.assertNotIn("flex-direction: column", css)
        self.assertIn(".loop-wordmark-name {", css)
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', script)
        self.assertIn("stActiveTheme-", script)
        self.assertIn("[theme.light]", toml)
        self.assertIn("[theme.dark]", toml)
        self.assertNotIn('base = "light"', toml)
        self.assertNotIn('base = "dark"', toml)
        self.assertIn("inject_brand_chrome()", Path(self.app.__file__).read_text(encoding="utf-8"))
        self.assertIn("st.markdown(brand_css()", Path(self.app.__file__).read_text(encoding="utf-8"))
        self.assertIn("html_fn(script", Path(self.app.__file__).read_text(encoding="utf-8"))
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("    render_brand_header()"), 1)
        self.assertIn('initial_sidebar_state="collapsed"', source)
        self.assertIn('"loop-glasses-light.svg"', source)
        self.assertNotIn('"loop-glasses.png"', source)
        self.assertNotIn('"loop-icon-light.png"', source)
        self.assertIn("Open LOOP sidebar", source)
        self.assertIn("stAppDeployButton", css)
        self.assertIn("scale(0.97)", css)
        self.assertIn("max-width: 760px", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("prefers-reduced-transparency", css)
        self.assertIn("prefers-contrast: more", css)
        self.assertIn("letter-spacing: 0.18em", css)
        self.assertIn("loop-tag-swatch", css)
        self.assertIn("loop-delta-up", css)
        self.assertIn('font = "Inter"', toml)
        self.assertIn("st.header(selected)", source)
        self.assertNotIn('st.title(f"Daily Loop: {selected}")', source)
        self.assertIn('st.header("The Loop")', source)
        self.assertIn("Search saved stories", source)
        self.assertIn("**Filters**", source)
        colors = list(self.app.TAG_COLORS.values())
        self.assertEqual(len(self.app.TAG_COLORS), 6)
        self.assertEqual(len(set(colors)), 6)
        for tag, color in self.app.TAG_COLORS.items():
            self.assertIn(color, css)
            self.assertIn(color, self.app.tag_hashtag_html(tag))
        with TemporaryDirectory() as temp_dir:
            bad = Path(temp_dir) / "loop-banner.svg"
            bad.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg">Daily Loop \xb7 The Loop</svg>')
            self.assertFalse(self.app.static_asset_is_utf8(bad))
            image = self.app.st.image
            image.reset_mock()
            self.assertFalse(self.app.show_static_image(bad, use_container_width=True))
            image.assert_not_called()
            missing = Path(temp_dir) / "missing.svg"
            self.assertFalse(self.app.show_static_image(missing))
            image.side_effect = UnicodeDecodeError("utf-8", b"\xb7", 0, 1, "invalid")
            ok = Path(temp_dir) / "ok.svg"
            ok.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
            self.assertFalse(self.app.show_static_image(ok))

    def test_generation_banners_and_lock_detection(self):
        today = "2026-10-24"
        self.assertEqual(
            self.app.generating_banner(today),
            "Briefing in progress… Today's briefing (2026-10-24) is generating in the background.",
        )
        self.assertEqual(
            self.app.ready_banner(today),
            "Today's briefing (2026-10-24) is ready. Refresh to load it.",
        )
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertIn('st.button("Refresh", key="loop_refresh_briefing")', source)
        self.assertIn("awaiting_refresh", source)
        with TemporaryDirectory() as temp_dir:
            lock = Path(temp_dir) / "briefing.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")
            self.assertTrue(self.app.is_briefing_generating(lock))
            lock.write_text("99999999", encoding="utf-8")
            self.assertFalse(self.app.is_briefing_generating(lock))

    def test_tab_titles_are_daily_loop_and_the_loop(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertEqual(self.app.TAB_DAILY, "Daily Loop")
        self.assertEqual(self.app.TAB_LOOP, "The Loop")
        self.assertIn("st.tabs([TAB_DAILY, TAB_LOOP])", source)
        self.assertIn("st.header(selected)", source)
        self.assertIn('st.header("The Loop")', source)
        self.assertNotIn("Daily Briefings", source)
        self.assertNotIn("The Loop Explorer", source)

    def test_search_stories_date_range_year_month_day(self):
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
                        "October policy",
                        "https://example.com/oct",
                        "Example News",
                        "",
                        '["US Politics"]',
                    ),
                    (
                        "2026-09-15",
                        "September policy",
                        "https://example.com/sep",
                        "Example News",
                        "",
                        '["US Politics"]',
                    ),
                    (
                        "2025-10-15",
                        "Prior year",
                        "https://example.com/prior",
                        "Example News",
                        "",
                        '["US Politics"]',
                    ),
                ],
            )
            connection.commit()
            connection.close()
            by_year = self.app.search_stories(str(path), "", "", "", year="2026")
            by_month = self.app.search_stories(
                str(path), "", "", "", year="2026", month="10"
            )
            by_day = self.app.search_stories(
                str(path), "", "", "", year="2026", month="10", day="15"
            )
            blank = self.app.search_stories(str(path), "", "", "")
            source = Path(self.app.__file__).read_text(encoding="utf-8")

        self.assertEqual(
            [row["headline"] for row in by_year],
            ["October policy", "September policy"],
        )
        self.assertEqual([row["headline"] for row in by_month], ["October policy"])
        self.assertEqual([row["headline"] for row in by_day], ["October policy"])
        self.assertEqual(len(blank), 3)
        self.assertIn("AND published_date = ?", source)
        self.assertIn("AND published_date LIKE ?", source)
        self.assertNotIn("AND published_date = '{", source)

    def test_daily_loop_date_default_and_loop_search_form(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertIn('st.selectbox("Briefing date"', source)
        self.assertIn("key=\"daily_loop_date\"", source)
        self.assertIn('st.form("loop_search_form")', source)
        self.assertIn('st.form_submit_button("Search", type="primary")', source)
        self.assertNotIn("on_change=_enter_loop_focus", source)
        self.assertEqual(
            self.app.default_briefing_date(
                ["2026-10-30", "2026-10-24"], "2026-10-30", generating=False
            ),
            "2026-10-30",
        )
        self.assertEqual(
            self.app.default_briefing_date(
                ["2026-10-30", "2026-10-24"], "2026-10-30", generating=True
            ),
            "2026-10-24",
        )
        self.assertEqual(
            self.app.default_briefing_date(
                ["2026-10-24"], "2026-10-30", generating=False
            ),
            "2026-10-24",
        )
        self.assertIsNone(self.app.default_briefing_date([], "2026-10-30"))


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
                "tags": ["Market Valuations"],
                "ai_summary": "Primary copy.",
            },
            {
                "published_date": "2026-10-15",
                "headline": "  RATES   rise ",
                "url": "https://example.com/cnbc",
                "source": "CNBC",
                "tags": ["Market Valuations"],
                "ai_summary": "Duplicate copy.",
            },
            {
                "published_date": "2026-10-15",
                "headline": "Rates rise",
                "url": "https://example.com/reuters",
                "source": "Reuters",
                "tags": ["Market Valuations"],
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
            "## Market Valuations\n"
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
