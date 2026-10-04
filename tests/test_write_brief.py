import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from write_brief import render_brief, section_for_story


def story(headline: str, topics: list[str]) -> dict[str, object]:
    return {
        "headline": headline,
        "source": "Example News",
        "link": "https://example.com/story",
        "published_at": "Today",
        "topics": topics,
    }


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
                story("Rates rise", ["policy"]),
                story("Oil rises", ["oil", "energy"]),
            ]},
            "2026-09-20",
        )

        self.assertIn("# AI Market Briefing — September 20, 2026", briefing)
        self.assertLess(briefing.index("## Policy & economics"), briefing.index("## Energy"))
        self.assertIn("[Rates rise](https://example.com/story)", briefing)
        self.assertIn("Topics: oil, energy", briefing)
        self.assertNotIn("## Technology", briefing)


if __name__ == "__main__":
    unittest.main()
