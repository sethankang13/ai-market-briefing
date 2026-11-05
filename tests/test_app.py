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
        self.assertIn("tags LIKE ?", source)
        self.assertIn("AND source = ?", source)
        self.assertIn("AND (headline LIKE ? OR ai_summary LIKE ?)", source)
        self.assertNotIn("AND tags LIKE '%", source)
        self.assertNotIn(f"LIKE '%{{", source)
        self.assertIn(
            "published_date, headline, url, source, sub_feed, tags, ai_summary",
            source,
        )
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
        self.assertEqual(
            self.app.read_query_source({"source": "Politico"}),
            "Politico",
        )
        self.assertIsNone(self.app.read_query_source({}))
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
        self.assertIn("http://127.0.0.1:8501/?loop=1&amp;tag=US+Politics", chips)
        self.assertIn('target="_self"', chips)
        rewritten = self.app.display_brief_markdown(
            'chip <a href="http://127.0.0.1:8501/?tag=US+Politics">#US Politics</a>\n'
        )
        self.assertIn("?loop=1&tag=US+Politics", rewritten)
        self.assertNotIn("?tag=US+Politics", rewritten.replace("?loop=1&tag=US+Politics", ""))
        self.assertIn("tag=US+Politics", chips)
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
        self.assertIn('<p class="loop-glance-line">', displayed)
        self.assertIn(
            '<a class="loop-glance" href="#us-politics">US Politics</a>: '
            '<a href="https://example.com/a" target="_blank" rel="noopener noreferrer">'
            "Apple may try…</a>, "
            '<a href="https://example.com/b" target="_blank" rel="noopener noreferrer">'
            "States take steps…</a></p>",
            displayed,
        )
        self.assertNotIn(
            '- <a class="loop-glance" href="#us-politics">US Politics</a> [Apple may try…]',
            displayed,
        )
        self.assertNotIn("- <a class=\"loop-glance\"", displayed)
        snapshot, glance, rest = self.app.split_daily_brief_sections(displayed)
        self.assertIn("## Market Snapshot", snapshot)
        self.assertIn("loop-delta-up", snapshot)
        self.assertNotIn("## At a Glance", snapshot)
        self.assertIn("## At a Glance", glance)
        self.assertIn("Apple may try…", glance)
        self.assertIn("States take steps…", glance)
        self.assertIn('href="https://example.com/a"', glance)
        self.assertIn('href="https://example.com/b"', glance)
        self.assertNotIn("## Market Snapshot", glance)
        self.assertNotIn("---", glance)
        self.assertNotIn("## At a Glance", rest)
        self.assertNotIn("## Market Snapshot", rest)
        self.assertIn("---", rest)

    def test_display_rewrites_stacked_glance_bullets_into_tag_lines(self):
        displayed = self.app.display_brief_markdown(
            "# Looping... (2026-10-23)\n\n"
            "## At a Glance\n\n"
            '- <a class="loop-glance" href="#us-politics">US Politics</a> [Apple may try…](https://example.com/a)\n'
            '- <a class="loop-glance" href="#us-politics">US Politics</a> [States take steps…](https://example.com/b)\n'
            '- <a class="loop-glance" href="#market-valuations">Market Valuations</a> [AI inference startup…](https://example.com/c)\n'
            "\n---\n"
        )
        self.assertIn('<p class="loop-glance-line">', displayed)
        self.assertEqual(displayed.count('<p class="loop-glance-line">'), 2)
        self.assertNotIn("- <a class=\"loop-glance\"", displayed)
        self.assertIn("Apple may try…", displayed)
        self.assertIn("States take steps…", displayed)
        self.assertIn("AI inference startup…", displayed)
        politics = next(
            line
            for line in displayed.splitlines()
            if "loop-glance-line" in line and "US Politics" in line
        )
        valuations = next(
            line
            for line in displayed.splitlines()
            if "loop-glance-line" in line and "Market Valuations" in line
        )
        self.assertIn("Apple may try…", politics)
        self.assertIn("States take steps…", politics)
        self.assertNotIn("AI inference startup…", politics)
        self.assertIn("AI inference startup…", valuations)

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
        compact_css = css.replace(" ", "").lower()
        self.assertIn("color:#f7f6f2!important", compact_css)
        self.assertIn('html[data-loop-theme="light"] [data-testid="stFormSubmitButton"] button', css)
        self.assertIn('html[data-loop-theme="dark"] [data-testid="stFormSubmitButton"] button', css)
        self.assertIn("[data-testid=\"stFormSubmitButton\"] button p", css)
        self.assertIn("[data-testid=\"stBaseButton-secondary\"]", css)
        self.assertIn("font-style: italic", css)
        self.assertIn("loop-glance-body", css)
        self.assertIn("loop-glance-line", css)
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
        self.assertIn("paintSearch", source)
        self.assertIn("loop-glance-body", source)
        self.assertIn("loop-glance-line", source)
        self.assertIn("stAppDeployButton", css)
        self.assertIn("scale(0.97)", css)
        self.assertNotIn("max-width: 760px", css)
        self.assertIn("max-width: none !important", css)
        self.assertIn('layout="wide"', source)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("prefers-reduced-transparency", css)
        self.assertIn("prefers-contrast: more", css)
        self.assertIn("letter-spacing: 0.18em", css)
        self.assertIn("loop-tag-swatch", css)
        self.assertIn("rgba(0, 0, 0, 0.06)", css)
        self.assertIn("text-decoration: underline", css)
        self.assertIn("apply_tag_in_focus", source)
        self.assertIn("apply_source_in_focus", source)
        self.assertIn("in_focus_heading_html", source)
        self.assertIn("loop-in-focus-tag", css)
        self.assertIn("stHeaderActionElements", css)
        self.assertIn("loop-feed-parent", css)
        self.assertIn('urlencode({"loop": "1", "source": publisher})', source)
        self.assertIn('target="_self"', source)
        self.assertNotIn("st.header(in_focus_title", source)
        heading = self.app.in_focus_heading_html("US Politics", "", "", "", "", "")
        self.assertIn("In Focus: ", heading)
        self.assertIn('class="loop-in-focus-tag"', heading)
        self.assertIn("US Politics", heading)
        self.assertIn("text-decoration-color:#9B8AB8", heading)
        self.assertNotIn('class="loop-in-focus-tag">In Focus', heading)
        self.assertIn("search_stories_page", source)
        self.assertIn("SEARCH_PAGE_SIZE = 20", source)
        self.assertIn("totalPages", source)
        self.assertIn("loop-delta-up", css)
        self.assertIn(".loop-delta-up { color: #2F7D4F !important; }", css)
        self.assertIn(".loop-delta-down { color: #C04545 !important; }", css)
        self.assertIn("split_daily_brief_sections", source)
        self.assertIn("st.columns((2, 1)", source)
        self.assertIn("tag_col, source_col = st.columns(2)", source)
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
        self.assertEqual(source.count("st.tabs([TAB_DAILY, TAB_LOOP])"), 1)
        self.assertNotIn("st.tabs([TAB_LOOP, TAB_DAILY])", source)
        self.assertIn("clear_loop_query_params", source)
        self.assertIn('data-loop-select-tab="The Loop"', source)
        self.assertIn("loop_select_tab", source)
        self.assertIn("loop_restore_tab", source)
        self.assertIn("loopActiveTab", source)
        self.assertIn("__loopTabLockUntil", source)
        self.assertIn("tabLockActive", source)
        self.assertIn("setTimeout(function () {", source)
        self.assertIn('addEventListener("pointerdown"', source)
        self.assertIn("armFrameFocus", source)
        self.assertNotIn("lockTabs(1000)", source)
        self.assertIn(".assign(href)", source)
        self.assertIn("retargetLoopLinks", source)
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

    def test_search_stories_page_returns_twenty_and_totals(self):
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
                    sub_feed TEXT,
                    full_text TEXT,
                    ai_summary TEXT,
                    tags TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO stories (published_date, headline, url, source, sub_feed, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        "2026-11-01",
                        f"Story {index}",
                        f"https://example.com/{index}",
                        "Politico" if index % 2 else "Reuters",
                        "Elections & Campaigns" if index % 2 else "Tech & Hardware",
                        '["US Politics"]' if index % 2 else '["Tech & Innovation"]',
                    )
                    for index in range(25)
                ],
            )
            connection.commit()
            connection.close()
            page_one = self.app.search_stories_page(str(path), "", "", "", page=1)
            page_two = self.app.search_stories_page(str(path), "", "", "", page=2)
            by_child = self.app.search_stories(
                str(path), "", "Elections & Campaigns", ""
            )
            by_parent = self.app.search_stories(str(path), "", "Politico", "")

        self.assertEqual(page_one["page"], 1)
        self.assertEqual(page_one["totalPages"], 2)
        self.assertEqual(page_one["totalCount"], 25)
        self.assertEqual(len(page_one["rows"]), 20)
        self.assertEqual(page_two["page"], 2)
        self.assertEqual(len(page_two["rows"]), 5)
        self.assertEqual(len(by_child), 12)
        self.assertEqual(len(by_parent), 12)

    def test_search_page_counts_unique_headlines_not_duplicate_rows(self):
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
                    sub_feed TEXT,
                    tags TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO stories (published_date, headline, url, source, sub_feed, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        "2026-10-23",
                        "Same story",
                        "https://example.com/same",
                        f"Source {index}",
                        "",
                        '["US Politics"]',
                    )
                    for index in range(20)
                ]
                + [
                    (
                        "2026-10-22",
                        f"Other {index}",
                        f"https://example.com/other-{index}",
                        "Reuters",
                        "",
                        '["Tech & Innovation"]',
                    )
                    for index in range(3)
                ],
            )
            connection.commit()
            connection.close()
            page = self.app.search_stories_page(str(path), "", "", "", page=1)
            groups = self.app.group_stories_by_headline(page["rows"])

        self.assertEqual(page["totalCount"], 4)
        self.assertEqual(page["totalPages"], 1)
        self.assertEqual(len(groups), 4)

    def test_search_matches_hyphenated_legacy_tags(self):
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
                    sub_feed TEXT,
                    tags TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO stories (published_date, headline, url, source, sub_feed, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "2026-10-22",
                    "Legacy valuation",
                    "https://example.com/legacy",
                    "FT, WSJ & Bloomberg Proxy",
                    "Markets",
                    '["Market-Valuations"]',
                ),
            )
            connection.commit()
            connection.close()
            rows = self.app.search_stories(str(path), "Market Valuations", "", "")

        self.assertEqual([row["headline"] for row in rows], ["Legacy valuation"])

    def test_daily_loop_date_default_and_loop_search_form(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        self.assertIn('st.selectbox("Briefing date"', source)
        self.assertIn("key=\"daily_loop_date\"", source)
        self.assertIn('st.form("loop_search_form")', source)
        self.assertIn('st.form_submit_button("Search", type="primary")', source)
        self.assertIn("setdefault(key, \"\")", source)
        self.assertIn("tag_col, source_col = st.columns(2)", source)
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
