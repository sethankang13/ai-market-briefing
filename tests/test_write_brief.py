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
    glance_phrase,
    latest_briefing_source,
    normalize_headline,
    render_brief,
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
            TAG_WEIGHTS["Legislation-&-Policy"],
            TAG_WEIGHTS["Enterprise-Adoption"],
        )
        self.assertEqual(
            primary_tag(["Enterprise-Adoption", "Legislation-&-Policy"]),
            "Legislation-&-Policy",
        )
        self.assertEqual(
            section_for_story(
                story("Adoption and policy", ["Enterprise-Adoption", "Legislation-&-Policy"])
            ),
            "Legislation-&-Policy",
        )
        self.assertEqual(
            section_for_story(story("New model", ["Foundation-Models"])),
            "Foundation-Models",
        )

    def test_tag_archive_url_encodes_ampersand_for_local_streamlit(self):
        url = tag_archive_url("Legislation-&-Policy")
        self.assertTrue(url.startswith(TAG_ARCHIVE_BASE))
        parsed = urlparse(url)
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, 8501)
        self.assertEqual(parse_qs(parsed.query)["tag"], ["Legislation-&-Policy"])
        self.assertIn("Legislation-%26-Policy", url)
        chip = tag_hashtag_html("Legislation-&-Policy")
        self.assertIn("#Legislation-&amp;-Policy", chip)
        self.assertIn(TAG_COLORS["Legislation-&-Policy"], chip)
        self.assertIn('href="http://127.0.0.1:8501/?tag=Legislation-%26-Policy"', chip)

    def test_section_titles_are_plain_headings_not_colored_links(self):
        heading = tag_heading_markdown("Legislation-&-Policy")
        self.assertIn("## Legislation-&-Policy", heading)
        self.assertIn(f'<a id="{tag_section_id("Legislation-&-Policy")}"></a>', heading)
        self.assertNotIn("style=", heading)
        self.assertNotIn("127.0.0.1:8501", heading)
        self.assertNotIn(TAG_COLORS["Legislation-&-Policy"], heading)

    def test_brief_groups_stories_and_keeps_the_source_link(self):
        briefing = render_brief(
            {
                "stories": [
                    story("Bill advances", ["Legislation-&-Policy"], "The bill can change compliance."),
                    story("Model release", ["Foundation-Models"], "Benchmarks may shift adoption."),
                ],
                "tag_notes": {
                    "Legislation-&-Policy": "Policy pattern from today's bill headline.",
                    "Foundation-Models": "Model pattern from today's release headline.",
                },
                "daily_summary": "A policy bill and a model release landed the same day.",
                "research_radar": ["Bill markup", "Model evals"],
            },
            "2026-09-20",
        )

        self.assertIn("# Looping... (2026-09-20)", briefing)
        self.assertIn("## Market Snapshot", briefing)
        snapshot_at = briefing.index("## Market Snapshot")
        policy_at = briefing.index("## Legislation-&-Policy")
        self.assertLess(snapshot_at, policy_at)
        self.assertIn("- Fed Funds:", briefing)
        self.assertIn("- S&P 500:", briefing)
        self.assertIn("- Nasdaq:", briefing)
        self.assertIn("- Dow:", briefing)
        self.assertLess(
            briefing.index("## Legislation-&-Policy"),
            briefing.index("## Foundation-Models"),
        )
        glance_at = briefing.index("## At a Glance")
        summary_at = briefing.index("## Daily Summary")
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
        self.assertNotIn("## Enterprise-Adoption", briefing)
        bill_line = next(
            line for line in briefing.splitlines() if line.startswith("- [Bill advances](")
        )
        self.assertIn("tag=Legislation-%26-Policy", bill_line)
        self.assertIn(TAG_COLORS["Legislation-&-Policy"], bill_line)
        policy_heading = next(
            line for line in briefing.splitlines() if line == "## Legislation-&-Policy"
        )
        self.assertNotIn("style=", policy_heading)
        self.assertNotIn("127.0.0.1", policy_heading)

    def test_original_headline_leads_even_when_ai_headline_is_present(self):
        briefing = render_brief(
            {
                "stories": [
                    story(
                        "Bill advances",
                        ["Legislation-&-Policy", "Enterprise-Adoption"],
                        "The bill can change compliance.",
                        ai_headline="A policy shift for enterprise AI",
                    )
                ],
                "tag_notes": {
                    "Legislation-&-Policy": "Shared policy pattern.",
                    "Enterprise-Adoption": "Shared adoption pattern.",
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
        self.assertIn("## Legislation-&-Policy", briefing)
        self.assertNotIn("## Enterprise-Adoption", briefing)
        self.assertIn("tag=Legislation-%26-Policy", title_line)
        self.assertIn("tag=Enterprise-Adoption", title_line)
        self.assertIn(TAG_COLORS["Enterprise-Adoption"], title_line)
        self.assertLess(
            briefing.index("- [Bill advances](https://example.com/story)"),
            briefing.index("Why it might matter / pattern: Shared policy pattern."),
        )
        glance = briefing[briefing.index("## At a Glance"):briefing.index("## Legislation-&-Policy")]
        self.assertIn(
            'href="#legislation-policy" style="color:#fff;font-style:italic;text-decoration:none">Legislation-&amp;-Policy</a>:',
            glance,
        )
        self.assertNotIn("Enterprise-Adoption", glance)
        self.assertNotIn("### [#", glance)

    def test_missing_ai_summary_does_not_write_pending_placeholder(self):
        briefing = render_brief(
            {"stories": [story("Bill advances", ["Legislation-&-Policy"])]},
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
                "stories": [story("Bill advances", ["Legislation-&-Policy"], "Policy copy.")],
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
        self.assertIn("- S&P 500: 5,123.45 (-0.42%)", briefing)
        self.assertIn("- Nasdaq: fetch failed", briefing)
        self.assertIn("- Dow: 42,000.00 (+0.10%)", briefing)
        self.assertNotIn("timeout", briefing)

    def test_daily_summary_follows_tag_sections_and_does_not_need_ai_summary(self):
        briefing = render_brief(
            {
                "stories": [story("Bill advances", ["Legislation-&-Policy"])],
                "tag_notes": {
                    "Legislation-&-Policy": "The bill continues a 14-day policy cluster."
                },
                "daily_summary": "Policy cluster from RSS headlines.",
                "research_radar": ["Follow the bill markup."],
            },
            "2026-10-23",
        )
        snapshot_at = briefing.index("## Market Snapshot")
        glance_at = briefing.index("## At a Glance")
        policy_at = briefing.index("## Legislation-&-Policy")
        summary_at = briefing.index("## Daily Summary")
        self.assertLess(snapshot_at, glance_at)
        self.assertLess(glance_at, policy_at)
        self.assertLess(policy_at, summary_at)
        self.assertIn("- [Bill advances](https://example.com/story)", briefing)
        self.assertIn("Research topics to look into more", briefing)
        self.assertIn("1. Follow the bill markup.", briefing)
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
                    story("Bill advances today in committee", ["Legislation-&-Policy"], "Policy copy."),
                    story("Model release", ["Foundation-Models"], "Model copy."),
                ]
            },
            "2026-10-21",
        )
        glance_at = briefing.index("## At a Glance")
        snapshot_at = briefing.index("## Market Snapshot")
        policy_at = briefing.index("## Legislation-&-Policy")
        glance = briefing[glance_at:policy_at]
        self.assertLess(snapshot_at, glance_at)
        self.assertLess(glance_at, policy_at)
        self.assertIn("[Bill advances today…](https://example.com/story)", glance)
        self.assertIn("[Model release…](https://example.com/story)", glance)
        self.assertNotIn("- [Bill advances today in committee](https://example.com/story)", glance)
        self.assertIn("- [Bill advances today in committee](https://example.com/story)", briefing[policy_at:])
        self.assertNotIn('<a id="bill-advances"></a>', briefing)
        self.assertEqual(slugify("Legislation-&-Policy"), "legislation-policy")
        policy_line = next(
            line
            for line in glance.splitlines()
            if "legislation-policy" in line and "Bill advances today…" in line
        )
        self.assertTrue(policy_line.startswith('<a href="#legislation-policy"'))
        self.assertIn('style="color:#fff;font-style:italic;text-decoration:none"', policy_line)
        self.assertIn(">Legislation-&amp;-Policy</a>:", policy_line)
        self.assertNotIn("#Legislation", policy_line)
        self.assertNotIn("### ", glance)
        self.assertNotIn("8501", policy_line)
        self.assertNotIn("text-decoration:underline", policy_line)
        model_line = next(
            line for line in glance.splitlines() if "Model release…" in line
        )
        self.assertIn("[Bill advances today…](https://example.com/story)", policy_line)
        self.assertIn("[Model release…](https://example.com/story)", model_line)

    def test_duplicate_headlines_are_grouped_as_also_covered_by(self):
        first = story("Rates rise", ["Market-Valuations"], "Primary copy.")
        first["source"] = "Reuters"
        second = story("  RATES   rise ", ["Market-Valuations"], "Duplicate copy.")
        second["source"] = "CNBC"
        third = story("Rates rise", ["Market-Valuations"], "Same source again.")
        third["source"] = "Reuters"
        briefing = render_brief(
            {
                "stories": [first, second, third],
                "tag_notes": {"Market-Valuations": "Valuation pattern from the rates cluster."},
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


if __name__ == "__main__":
    unittest.main()
