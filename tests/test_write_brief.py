import sys
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tag_stories import TAG_WEIGHTS, primary_tag
from write_brief import (
    TAG_ARCHIVE_BASE,
    TAG_COLORS,
    concise_topic_label,
    copy_from_run,
    createGeminiResearchUrl,
    create_gemini_research_url,
    glance_phrase,
    latest_briefing_source,
    normalize_headline,
    render_brief,
    sanitize_markdown_text,
    section_for_story,
    slugify,
    tag_archive_url,
    tag_hashtag_html,
    tag_heading_markdown,
    tag_section_id,
)


def story(
    headline: str,
    tags: list[str],
    ai_summary: str | None = None,
    ai_headline: str | None = None,
) -> dict[str, object]:
    item = {
        "headline": headline,
        "source": "Example News",
        "link": "https://example.com/story",
        "published_at": "Today",
        "tags": tags,
    }
    if ai_summary is not None:
        item["ai_summary"] = ai_summary
    if ai_headline is not None:
        item["ai_headline"] = ai_headline
    return item


class WriteBriefTests(unittest.TestCase):
    def test_multi_tag_story_uses_one_highest_weight_section(self):
        self.assertGreater(
            TAG_WEIGHTS["US Politics"],
            TAG_WEIGHTS["Tech & Innovation"],
        )
        self.assertEqual(
            primary_tag(["Tech & Innovation", "US Politics"]),
            "US Politics",
        )
        self.assertEqual(
            section_for_story(
                story("Adoption and policy", ["Tech & Innovation", "US Politics"])
            ),
            "US Politics",
        )
        self.assertEqual(
            section_for_story(story("New model", ["Tech & Innovation"])),
            "Tech & Innovation",
        )

    def test_tag_archive_url_encodes_spaces_and_ampersands_for_local_streamlit(self):
        url = tag_archive_url("US Politics")
        self.assertTrue(url.startswith(TAG_ARCHIVE_BASE))
        parsed = urlparse(url)
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, 8501)
        self.assertEqual(parse_qs(parsed.query)["tag"], ["US Politics"])
        self.assertIn("US+Politics", url)
        self.assertEqual(slugify("US Politics"), "us-politics")
        chip = tag_hashtag_html("US Politics")
        self.assertIn("#US Politics", chip)
        self.assertNotIn("#US-Politics", chip)
        self.assertIn('class="loop-tag"', chip)
        self.assertIn("loop-tag-swatch", chip)
        self.assertIn(f"background-color:{TAG_COLORS['US Politics']}", chip)
        self.assertNotIn('style="color:', chip)
        self.assertIn('href="http://127.0.0.1:8501/?loop=1&amp;tag=US+Politics"', chip)
        self.assertIn('target="_self"', chip)
        labor = tag_archive_url("Labor & Economy")
        self.assertEqual(parse_qs(urlparse(labor).query)["tag"], ["Labor & Economy"])
        self.assertIn("Labor+%26+Economy", labor)
        self.assertIn("#Labor &amp; Economy", tag_hashtag_html("Labor & Economy"))

    def test_section_titles_are_plain_headings_not_colored_links(self):
        heading = tag_heading_markdown("US Politics")
        self.assertIn("## US Politics", heading)
        self.assertIn(f'<a id="{tag_section_id("US Politics")}"></a>', heading)
        self.assertNotIn("style=", heading)
        self.assertNotIn("127.0.0.1:8501", heading)
        self.assertNotIn(TAG_COLORS["US Politics"], heading)

    def test_brief_groups_stories_and_keeps_the_source_link(self):
        briefing = render_brief(
            {
                "stories": [
                    story("Bill advances", ["US Politics"], "The bill can change compliance."),
                    story("Model release", ["Tech & Innovation"], "Benchmarks may shift adoption."),
                ],
                "tag_notes": {
                    "US Politics": "Policy pattern from today's bill headline.",
                    "Tech & Innovation": "Model pattern from today's release headline.",
                },
                "daily_summary": "A policy bill and a model release landed the same day.",
                "research_radar": ["Bill markup", "Model evals"],
            },
            "2026-09-20",
        )

        self.assertIn("# Looping... (2026-09-20)", briefing)
        self.assertIn("## Market Snapshot", briefing)
        snapshot_at = briefing.index("## Market Snapshot")
        policy_at = briefing.index("## US Politics")
        self.assertLess(snapshot_at, policy_at)
        self.assertIn("- Fed Funds:", briefing)
        self.assertIn("- S&P 500:", briefing)
        self.assertIn("- Nasdaq:", briefing)
        self.assertIn("- Dow:", briefing)
        self.assertLess(
            briefing.index("## US Politics"),
            briefing.index("## Tech & Innovation"),
        )
        glance_at = briefing.index("## At a Glance")
        summary_at = briefing.index("## Daily Summary & Research Topics")
        self.assertLess(snapshot_at, glance_at)
        self.assertLess(glance_at, policy_at)
        self.assertLess(policy_at, summary_at)
        self.assertIn("- [Bill advances](https://example.com/story)", briefing)
        self.assertNotIn("*Tags:", briefing)
        self.assertNotIn("Why It Matters:", briefing)
        self.assertIn(
            "Why it might matter / pattern: Policy pattern from today's bill headline.",
            briefing,
        )
        self.assertIn(
            "Why it might matter / pattern: Model pattern from today's release headline.",
            briefing,
        )
        bill_line = next(
            line for line in briefing.splitlines() if line.startswith("- [Bill advances](")
        )
        self.assertIn("tag=US+Politics", bill_line)
        self.assertIn(TAG_COLORS["US Politics"], bill_line)
        policy_heading = next(
            line for line in briefing.splitlines() if line == "## US Politics"
        )
        self.assertNotIn("style=", policy_heading)
        self.assertNotIn("127.0.0.1", policy_heading)

    def test_original_headline_leads_even_when_ai_headline_is_present(self):
        briefing = render_brief(
            {
                "stories": [
                    story(
                        "Bill advances",
                        ["US Politics", "Tech & Innovation"],
                        "The bill can change compliance.",
                        ai_headline="A policy shift for enterprise AI",
                    )
                ],
                "tag_notes": {
                    "US Politics": "Shared policy pattern.",
                    "Tech & Innovation": "Shared adoption pattern.",
                },
                "daily_summary": "One story, two tags.",
            },
            "2026-09-20",
        )

        title_line = next(
            line for line in briefing.splitlines() if line.startswith("- [Bill advances](")
        )
        self.assertTrue(title_line.startswith("- [Bill advances]("))
        self.assertNotIn("A policy shift for enterprise AI", briefing)
        self.assertNotIn("*Tags:", briefing)
        self.assertNotIn("Why It Matters:", briefing)
        self.assertEqual(briefing.count("- [Bill advances](https://example.com/story)"), 1)
        self.assertIn("## US Politics", briefing)
        self.assertNotIn("## Tech & Innovation", briefing)
        self.assertIn("tag=US+Politics", title_line)
        self.assertIn("tag=Tech+%26+Innovation", title_line)
        self.assertIn(TAG_COLORS["Tech & Innovation"], title_line)
        self.assertLess(
            briefing.index("- [Bill advances](https://example.com/story)"),
            briefing.index("Why it might matter / pattern: Shared policy pattern."),
        )
        glance = briefing[briefing.index("## At a Glance"):briefing.index("## US Politics")]
        self.assertIn(
            'href="#us-politics">US Politics</a>: [Bill advances…]',
            glance,
        )
        self.assertNotIn("Tech & Innovation", glance)
        self.assertNotIn("### [#", glance)

    def test_missing_ai_summary_does_not_write_pending_placeholder(self):
        briefing = render_brief(
            {"stories": [story("Bill advances", ["US Politics"])]},
            "2026-09-20",
        )
        self.assertNotIn("AI Summary Pending", briefing)
        self.assertNotIn("AI Headline Pending", briefing)
        self.assertNotIn("AI headline pending", briefing)
        self.assertNotIn("AI Summary goes HERE", briefing)
        self.assertNotIn("Why It Matters:", briefing)
        self.assertIn("[Bill advances](https://example.com/story)", briefing)

    def test_market_snapshot_uses_explicit_failure_not_fake_numbers(self):
        briefing = render_brief(
            {
                "stories": [story("Bill advances", ["US Politics"], "Policy copy.")],
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
            },
            "2026-10-21",
        )
        self.assertIn("# Looping... (2026-10-21)", briefing)
        self.assertIn("- Fed Funds: 4.33%", briefing)
        self.assertIn("- S&P 500: 5,123.45 (", briefing)
        self.assertIn("-0.42%", briefing)
        self.assertIn("loop-delta-down", briefing)
        self.assertIn("- Nasdaq: fetch failed", briefing)
        self.assertIn("- Dow: 42,000.00 (", briefing)
        self.assertIn("+0.10%", briefing)
        self.assertIn("loop-delta-up", briefing)
        self.assertNotIn("#C04545", briefing)
        self.assertNotIn("#2F7D4F", briefing)
        self.assertNotIn("timeout", briefing)

    def test_sanitize_markdown_text_strips_inline_backticks(self):
        self.assertEqual(
            sanitize_markdown_text("The `S&P 500` rose after the `Fed` hold."),
            "The S&P 500 rose after the Fed hold.",
        )
        self.assertEqual(sanitize_markdown_text("No ticks here."), "No ticks here.")
        self.assertEqual(sanitize_markdown_text("`one` and `two`"), "one and two")
        notes, summary, radar = copy_from_run(
            {
                "stories": [story("Bill advances", ["US Politics"])],
                "tag_notes": {
                    "US Politics": "The `bill` continues a policy cluster."
                },
                "daily_summary": "Policy hit the `S&P 500` and quotes from `Powell`.",
                "research_radar": ["Follow the `markup`."],
            }
        )
        self.assertEqual(
            notes["US Politics"], "The bill continues a policy cluster."
        )
        self.assertEqual(
            summary, "Policy hit the S&P 500 and quotes from Powell."
        )
        self.assertEqual(radar, ["Follow the markup."])
        briefing = render_brief(
            {
                "stories": [story("Bill advances", ["US Politics"])],
                "tag_notes": {
                    "US Politics": "The `bill` continues a policy cluster."
                },
                "daily_summary": "Policy hit the `S&P 500`.",
                "research_radar": ["Follow the `markup`."],
            },
            "2026-10-23",
        )
        self.assertIn("The bill continues a policy cluster.", briefing)
        self.assertIn("Policy hit the S&P 500.", briefing)
        self.assertIn("Follow the markup", briefing)
        self.assertNotIn("`S&P 500`", briefing)
        self.assertNotIn("`bill`", briefing)
        self.assertNotIn("`markup`", briefing)

    def test_daily_summary_follows_tag_sections_and_does_not_need_ai_summary(self):
        briefing = render_brief(
            {
                "stories": [story("Bill advances", ["US Politics"])],
                "tag_notes": {
                    "US Politics": "The bill continues a 14-day policy cluster."
                },
                "daily_summary": "Policy cluster from RSS headlines.",
                "research_radar": ["Follow the bill markup."],
            },
            "2026-10-23",
        )
        snapshot_at = briefing.index("## Market Snapshot")
        glance_at = briefing.index("## At a Glance")
        policy_at = briefing.index("## US Politics")
        summary_at = briefing.index("## Daily Summary & Research Topics")
        self.assertLess(snapshot_at, glance_at)
        self.assertLess(glance_at, policy_at)
        self.assertLess(policy_at, summary_at)
        self.assertIn("- [Bill advances](https://example.com/story)", briefing)
        self.assertIn("**Ask Gemini:**", briefing)
        self.assertNotIn("Research topics to look into more", briefing)
        self.assertNotIn("1. Follow the bill markup.", briefing)
        self.assertIn("https://www.google.com/search?udm=50&amp;q=", briefing)
        self.assertNotIn("gemini.google.com/app?q=", briefing)
        self.assertIn("Follow the bill markup", briefing)
        self.assertNotIn("# The Loop: Macro Landscape", briefing)
        self.assertNotIn("Why It Matters:", briefing)
        self.assertNotIn("AI Summary Pending", briefing)

    def test_latest_briefing_source_prefers_summarized_over_selected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected = root / "selected"
            summarized = root / "summarized"
            selected.mkdir()
            summarized.mkdir()
            (selected / "2026-09-20.json").write_text("{}", encoding="utf-8")
            summarized_file = summarized / "2026-09-21.json"
            summarized_file.write_text("{}", encoding="utf-8")

            self.assertEqual(
                latest_briefing_source(summarized, selected),
                summarized_file,
            )

    def test_at_a_glance_uses_three_word_links_to_rss_and_jumps_to_sections(self):
        self.assertEqual(glance_phrase("Bill advances today in committee"), "Bill advances today…")
        self.assertEqual(glance_phrase("Rates rise"), "Rates rise…")
        briefing = render_brief(
            {
                "stories": [
                    story("Bill advances today in committee", ["US Politics"], "Policy copy."),
                    story("Model release", ["Tech & Innovation"], "Model copy."),
                ]
            },
            "2026-10-21",
        )
        glance_at = briefing.index("## At a Glance")
        snapshot_at = briefing.index("## Market Snapshot")
        policy_at = briefing.index("## US Politics")
        glance = briefing[glance_at:policy_at]
        self.assertLess(snapshot_at, glance_at)
        self.assertLess(glance_at, policy_at)
        self.assertIn("[Bill advances today…](https://example.com/story)", glance)
        self.assertIn("[Model release…](https://example.com/story)", glance)
        self.assertNotIn("- [Bill advances today in committee](https://example.com/story)", glance)
        self.assertIn("- [Bill advances today in committee](https://example.com/story)", briefing[policy_at:])
        self.assertNotIn('<a id="bill-advances"></a>', briefing)
        self.assertEqual(slugify("US Politics"), "us-politics")
        policy_line = next(
            line
            for line in glance.splitlines()
            if "us-politics" in line and "Bill advances today…" in line
        )
        tech_line = next(
            line
            for line in glance.splitlines()
            if "Tech" in line and "Model release…" in line
        )
        self.assertTrue(policy_line.startswith('<a class="loop-glance" href="#us-politics"'))
        self.assertIn(">US Politics</a>:", policy_line)
        self.assertNotIn("#US Politics", policy_line)
        self.assertNotIn("### ", glance)
        self.assertNotIn("8501", policy_line)
        self.assertNotIn("text-decoration:underline", policy_line)
        self.assertIn("[Bill advances today…](https://example.com/story)", policy_line)
        self.assertNotIn("[Model release…](https://example.com/story)", policy_line)
        self.assertIn("[Model release…](https://example.com/story)", tech_line)
        self.assertIn("Tech &amp; Innovation", tech_line)
        self.assertNotEqual(policy_line, tech_line)
        self.assertNotIn("- <a class=\"loop-glance\"", glance)

    def test_duplicate_headlines_are_grouped_as_also_covered_by(self):
        first = story("Rates rise", ["Market Valuations"], "Primary copy.")
        first["source"] = "Reuters"
        second = story("  RATES   rise ", ["Market Valuations"], "Duplicate copy.")
        second["source"] = "CNBC"
        third = story("Rates rise", ["Market Valuations"], "Same source again.")
        third["source"] = "Reuters"
        briefing = render_brief(
            {
                "stories": [first, second, third],
                "tag_notes": {"Market Valuations": "Valuation pattern from the rates cluster."},
                "daily_summary": "Rates were the market story.",
            },
            "2026-10-21",
        )

        self.assertEqual(normalize_headline("  RATES   rise "), "rates rise")
        self.assertEqual(briefing.count("- [Rates rise](https://example.com/story)"), 1)
        self.assertIn("[Rates rise…](https://example.com/story)", briefing)
        self.assertIn("also covered by [CNBC]", briefing)
        self.assertNotIn("also covered by [CNBC, Reuters]", briefing)
        self.assertNotIn("Duplicate copy.", briefing)
        self.assertNotIn("Why It Matters:", briefing)
        self.assertIn(
            "Why it might matter / pattern: Valuation pattern from the rates cluster.",
            briefing,
        )
        self.assertNotIn("- [Rates rise](#rates-rise)", briefing)
        self.assertNotIn("*Tags:", briefing)

    def test_create_gemini_research_url_encodes_the_full_prompt(self):
        from urllib.parse import unquote

        self.assertIs(createGeminiResearchUrl, create_gemini_research_url)
        self.assertEqual(concise_topic_label("Follow the bill markup."), "Follow the bill markup")
        url = createGeminiResearchUrl(
            "Follow the bill markup.",
            "Policy cluster from RSS headlines.",
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "www.google.com")
        self.assertEqual(parsed.path, "/search")
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("udm"), ["50"])
        encoded = url.split("udm=50&q=", 1)[1]
        self.assertIn("%20", encoded)
        self.assertNotIn("+", encoded)
        prompt = unquote(encoded)
        self.assertIn("Follow the bill markup.", prompt)
        self.assertIn("Policy cluster from RSS headlines.", prompt)
        self.assertIn("Executive summary", prompt)
        self.assertIn("Timeline", prompt)
        self.assertIn("Technical details", prompt)
        self.assertIn("Citations", prompt)


if __name__ == "__main__":
    unittest.main()
