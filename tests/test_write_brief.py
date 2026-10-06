import sys
from pathlib import Path
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from write_brief import latest_briefing_source, render_brief, section_for_story


def story(
    headline: str,
    topics: list[str],
    ai_summary: str | None = None,
    ai_headline: str | None = None,
) -> dict[str, object]:
    item = {
        "headline": headline,
        "source": "Example News",
        "link": "https://example.com/story",
        "published_at": "Today",
        "topics": topics,
    }
    if ai_summary is not None:
        item["ai_summary"] = ai_summary
    if ai_headline is not None:
        item["ai_headline"] = ai_headline
    return item


class WriteBriefTests(unittest.TestCase):
    def test_multi_topic_story_uses_one_primary_section(self):
        self.assertEqual(
            section_for_story(story("Rates and energy", ["energy", "policy"])),
            "Policy & economics",
        )
        self.assertEqual(
            section_for_story(story("Oil rises", ["oil", "energy"])),
            "Energy",
        )

    def test_brief_groups_stories_and_keeps_the_source_link(self):
        briefing = render_brief(
            {"stories": [
                story("Rates rise", ["policy"], "Policy changes can move rates."),
                story("Oil rises", ["oil", "energy"], "Energy prices may follow."),
            ]},
            "2026-09-20",
        )

        self.assertIn("# AI Market Briefing — September 20, 2026", briefing)
        self.assertLess(briefing.index("## Policy & economics"), briefing.index("## Energy"))
        self.assertIn("[Rates rise](https://example.com/story)", briefing)
        self.assertIn("Topics: oil, energy", briefing)
        self.assertIn("Why It Matters: Policy changes can move rates.", briefing)
        self.assertIn("Why It Matters: Energy prices may follow.", briefing)
        self.assertNotIn("## Technology", briefing)
        rates_bullet = next(line for line in briefing.splitlines() if "Rates rise" in line)
        self.assertTrue(rates_bullet.startswith("- [Rates rise]("))

    def test_ai_headline_leads_and_source_headline_follows(self):
        briefing = render_brief(
            {
                "stories": [
                    story(
                        "Rates rise",
                        ["policy"],
                        "Policy changes can move rates.",
                        ai_headline="Rate guidance is the market risk",
                    )
                ]
            },
            "2026-09-20",
        )

        ai_at = briefing.index("Rate guidance is the market risk")
        source_at = briefing.index("[Rates rise](https://example.com/story)")
        why_at = briefing.index("Why It Matters: Policy changes can move rates.")
        self.assertLess(ai_at, source_at)
        self.assertLess(source_at, why_at)
        self.assertLess(source_at, briefing.index("Example News · Today · Topics: policy"))

    def test_missing_ai_summary_uses_pending_placeholder(self):
        briefing = render_brief(
            {"stories": [story("Rates rise", ["policy"])]},
            "2026-09-20",
        )
        self.assertIn("Why It Matters: [AI Summary Pending: Rates rise]", briefing)

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


if __name__ == "__main__":
    unittest.main()
