import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tag_stories import enrich_story, has_all_topics, tags_for_text


class TagStoriesTests(unittest.TestCase):
    def test_valuation_matches_market_and_venture_tags(self):
        self.assertEqual(
            tags_for_text("Startup valuation jumps after earnings"),
            ["Market Valuations", "Venture & M&A"],
        )

    def test_description_can_add_a_tag_the_headline_misses(self):
        self.assertEqual(
            tags_for_text("Company update", "Senate passes the farm bill today."),
            ["US Politics"],
        )

    def test_us_politics_skips_generic_probes(self):
        self.assertEqual(
            tags_for_text("Company update", "Regulators opened an FTC probe."),
            [],
        )

    def test_tag_cap_prefers_domain_over_us_politics(self):
        tags = tags_for_text(
            "Congress debates an AI earnings merger valuation for Nvidia chips"
        )
        self.assertLessEqual(len(tags), 3)
        self.assertIn("Tech & Innovation", tags)
        self.assertIn("Market Valuations", tags)
        self.assertNotIn("US Politics", tags)

    def test_foundation_models_match_model_names(self):
        self.assertEqual(
            tags_for_text("Claude benchmark beats a Gemini model"),
            ["Tech & Innovation"],
        )

    def test_layoffs_match_the_labor_tag(self):
        self.assertIn("Labor & Economy", tags_for_text("AI layoffs hit the workforce"))
        self.assertIn("Labor & Economy", tags_for_text("Company announces lay-offs"))

    def test_unmatched_text_gets_an_empty_tag_list(self):
        self.assertEqual(tags_for_text("A remarkable art installation opens"), [])

    def test_enrichment_keeps_the_raw_story_fields(self):
        raw_story = {
            "headline": "Government policy bill advances",
            "description": "Enterprise SaaS teams are watching.",
            "source": "Example News",
            "link": "https://example.com/story",
            "published_at": "Today",
        }

        enriched_story = enrich_story(raw_story)

        self.assertEqual(enriched_story["source"], "Example News")
        self.assertEqual(enriched_story["description"], raw_story["description"])
        self.assertEqual(
            enriched_story["tags"],
            ["US Politics", "Tech & Innovation"],
        )
        self.assertNotIn("tags", raw_story)

    def test_a_combined_query_requires_every_tag(self):
        story = enrich_story(
            {
                "headline": "Copyright lawsuit follows data scraping",
                "description": "The EU AI Act investigation continues.",
            }
        )

        self.assertTrue(has_all_topics(story, {"Tech & Innovation"}))
        self.assertFalse(has_all_topics(story, {"US Politics", "Tech & Innovation"}))
        self.assertFalse(has_all_topics(story, {"US Politics", "Venture & M&A"}))


if __name__ == "__main__":
    unittest.main()
