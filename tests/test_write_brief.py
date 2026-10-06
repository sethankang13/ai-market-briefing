import sys
from pathlib import Path
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from write_brief import latest_briefing_source, render_brief, section_for_story


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
    def test_multi_tag_story_uses_one_primary_section(self):
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

    def test_brief_groups_stories_and_keeps_the_source_link(self):
        briefing = render_brief(
            {"stories": [
                story("Bill advances", ["Legislation-&-Policy"], "The bill can change compliance."),
                story("Model release", ["Foundation-Models"], "Benchmarks may shift adoption."),
            ]},
            "2026-09-20",
        )

        self.assertIn("# AI Market Briefing — September 20, 2026", briefing)
        self.assertLess(
            briefing.index("## Legislation-&-Policy"),
            briefing.index("## Foundation-Models"),
        )
        self.assertIn("[Bill advances](https://example.com/story)", briefing)
        self.assertIn("*Tags: #Foundation-Models*", briefing)
        self.assertIn("Why It Matters: The bill can change compliance.", briefing)
        self.assertIn("Why It Matters: Benchmarks may shift adoption.", briefing)
        self.assertNotIn("## Enterprise-Adoption", briefing)
        bill_line = next(line for line in briefing.splitlines() if "Bill advances" in line)
        self.assertTrue(bill_line.startswith("- [Bill advances]("))

    def test_ai_headline_leads_then_source_then_tags(self):
        briefing = render_brief(
            {
                "stories": [
                    story(
                        "Bill advances",
                        ["Legislation-&-Policy", "Enterprise-Adoption"],
                        "The bill can change compliance.",
                        ai_headline="A policy shift for enterprise AI",
                    )
                ]
            },
            "2026-09-20",
        )

        ai_at = briefing.index("A policy shift for enterprise AI")
        source_at = briefing.index("[Bill advances](https://example.com/story)")
        tags_at = briefing.index("*Tags: #Legislation-&-Policy #Enterprise-Adoption*")
        why_at = briefing.index("Why It Matters: The bill can change compliance.")
        self.assertLess(ai_at, source_at)
        self.assertLess(source_at, tags_at)
        self.assertLess(tags_at, why_at)

    def test_missing_ai_summary_uses_pending_placeholder(self):
        briefing = render_brief(
            {"stories": [story("Bill advances", ["Legislation-&-Policy"])]},
            "2026-09-20",
        )
        self.assertIn("Why It Matters: [AI Summary Pending: Bill advances]", briefing)

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
