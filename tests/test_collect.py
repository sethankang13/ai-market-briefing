import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import collect_stories


class CollectMergeAndCapTests(unittest.TestCase):
    def test_config_caps_each_feed_at_fifteen(self):
        self.assertEqual(collect_stories.MAX_ITEMS_PER_FEED, 15)
        stories = [
            {"headline": f"Story {index}", "source": "Reuters"}
            for index in range(20)
        ]
        capped = collect_stories.cap_feed_items(stories)
        self.assertEqual(len(capped), 15)
        self.assertEqual(capped[0]["headline"], "Story 0")
        self.assertEqual(capped[-1]["headline"], "Story 14")

    def test_merge_casefold_headlines_keeps_primary_and_secondary_sources(self):
        merged = collect_stories.merge_stories_by_headline(
            [
                {
                    "headline": "Fed Holds Rates",
                    "source": "Reuters",
                    "link": "https://example.com/reuters",
                },
                {
                    "headline": "fed holds rates",
                    "source": "CNBC",
                    "link": "https://example.com/cnbc",
                },
                {
                    "headline": "  FED HOLDS RATES ",
                    "source": "AP News",
                    "link": "https://example.com/ap",
                },
                {
                    "headline": "Other story",
                    "source": "Axios",
                    "link": "https://example.com/axios",
                },
            ]
        )
        self.assertEqual(len(merged), 2)
        primary = merged[0]
        self.assertEqual(primary["headline"], "Fed Holds Rates")
        self.assertEqual(primary["source"], "Reuters")
        self.assertEqual(primary["link"], "https://example.com/reuters")
        self.assertEqual(primary["secondary_sources"], ["CNBC", "AP News"])
        self.assertEqual(merged[1]["source"], "Axios")
        self.assertEqual(merged[1]["secondary_sources"], [])
