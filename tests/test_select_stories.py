import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from select_stories import score_story, select_stories


def story(headline: str, topics: list[str]) -> dict[str, object]:
    return {"headline": headline, "topics": topics}


class SelectStoriesTests(unittest.TestCase):
    def test_stories_rank_by_the_sum_of_their_topic_scores(self):
        oil_story = story("Oil rises", ["oil", "energy"])
        policy_story = story("Rates rise", ["policy"])

        self.assertEqual(score_story(oil_story), 8)
        self.assertEqual(select_stories([policy_story, oil_story]), [
            {
                **oil_story,
                "selection_score": 8,
                "selection_reason": "Matched: oil, energy.",
            },
            {
                **policy_story,
                "selection_score": 4,
                "selection_reason": "Matched: policy.",
            },
        ])

    def test_misc_never_displaces_a_consequential_story(self):
        stories = [
            story("Interesting aside", ["misc"]),
            story("Policy one", ["policy"]),
            story("Policy two", ["policy"]),
            story("Policy three", ["policy"]),
            story("Policy four", ["policy"]),
            story("Policy five", ["policy"]),
        ]

        selected = select_stories(stories)

        self.assertEqual([item["headline"] for item in selected], [
            "Policy one",
            "Policy two",
            "Policy three",
            "Policy four",
            "Policy five",
            "Interesting aside",
        ])
        self.assertEqual(selected[-1]["selection_score"], 0)
        self.assertEqual(
            selected[-1]["selection_reason"],
            "Interesting aside; no current market-topic rule matched.",
        )

    def test_misc_fills_one_unused_slot(self):
        selected = select_stories([
            story("Policy", ["policy"]),
            story("Interesting aside", ["misc"]),
        ])

        self.assertEqual([item["headline"] for item in selected], ["Policy", "Interesting aside"])
        self.assertEqual(selected[1]["selection_score"], 0)

    def test_each_present_tag_keeps_its_highest_story(self):
        stories = [
            story("Oil one", ["oil", "energy"]),
            story("Oil two", ["oil", "energy"]),
            story("Oil three", ["oil", "energy"]),
            story("Oil four", ["oil", "energy"]),
            story("Oil five", ["oil", "energy"]),
            story("Oil six", ["oil", "energy"]),
            story("Rates", ["policy"]),
            story("Chips", ["technology"]),
            story("Solar", ["energy"]),
            story("Aside", ["misc"]),
            story("Another aside", ["misc"]),
        ]

        selected = select_stories(stories)
        headlines = [item["headline"] for item in selected]

        self.assertEqual(
            headlines,
            [
                "Oil one",
                "Oil two",
                "Oil three",
                "Oil four",
                "Oil five",
                "Rates",
                "Chips",
                "Aside",
            ],
        )
        rates = next(item for item in selected if item["headline"] == "Rates")
        self.assertEqual(rates["selection_score"], 4)
        self.assertEqual(rates["selection_reason"], "Matched: policy.")
        self.assertNotIn("Solar", headlines)
        self.assertNotIn("Another aside", headlines)

    def test_a_missing_tag_adds_nothing(self):
        selected = select_stories([
            story("Rates", ["policy"]),
            story("Oil rises", ["oil", "energy"]),
        ])

        self.assertEqual(
            [item["headline"] for item in selected],
            ["Oil rises", "Rates"],
        )


if __name__ == "__main__":
    unittest.main()
