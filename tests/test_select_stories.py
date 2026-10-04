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
            "Policy one", "Policy two", "Policy three", "Policy four", "Policy five"
        ])

    def test_misc_fills_one_unused_slot(self):
        selected = select_stories([
            story("Policy", ["policy"]),
            story("Interesting aside", ["misc"]),
        ])

        self.assertEqual([item["headline"] for item in selected], ["Policy", "Interesting aside"])
        self.assertEqual(selected[1]["selection_score"], 0)


if __name__ == "__main__":
    unittest.main()
