import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tag_stories import enrich_story, has_all_topics, tags_for_headline


class TagStoriesTests(unittest.TestCase):
    def test_oil_is_part_of_the_broader_energy_sector(self):
        self.assertEqual(tags_for_headline("Crude oil prices rise"), ["oil", "energy"])
        self.assertEqual(tags_for_headline("Solar energy investment grows"), ["energy"])

    def test_technology_can_overlap_with_energy(self):
        headline = "New solar technology improves battery storage"
        self.assertEqual(tags_for_headline(headline), ["energy", "technology"])

    def test_policy_catches_rates_and_trade_measures(self):
        self.assertEqual(
            tags_for_headline("Fed signals interest rates may remain elevated"),
            ["policy"],
        )

    def test_policy_requires_a_clear_tax_policy_phrase(self):
        self.assertEqual(tags_for_headline("Government announces new taxes"), ["policy"])
        self.assertEqual(
            tags_for_headline("Owner criticised over tax exile"),
            ["misc"],
        )

    def test_unmatched_headline_is_preserved_as_misc(self):
        self.assertEqual(
            tags_for_headline("A remarkable art installation opens downtown"),
            ["misc"],
        )
        self.assertEqual(
            tags_for_headline("New tariffs raise trade concerns"),
            ["policy"],
        )

    def test_enrichment_keeps_the_raw_story_fields(self):
        raw_story = {
            "headline": "Energy markets react to new technology",
            "source": "Example News",
            "link": "https://example.com/story",
            "published_at": "Today",
        }

        enriched_story = enrich_story(raw_story)

        self.assertEqual(enriched_story["source"], "Example News")
        self.assertEqual(enriched_story["topics"], ["energy", "technology"])

    def test_a_combined_query_requires_every_tag(self):
        story = enrich_story({"headline": "Crude oil and energy technology"})

        self.assertTrue(has_all_topics(story, {"oil", "energy"}))
        self.assertFalse(has_all_topics(story, {"oil", "technology", "policy"}))


if __name__ == "__main__":
    unittest.main()
