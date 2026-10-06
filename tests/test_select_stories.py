import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from select_stories import score_story, select_stories


def story(headline: str, tags: list[str]) -> dict[str, object]:
    return {"headline": headline, "tags": tags}


class SelectStoriesTests(unittest.TestCase):
    def test_stories_rank_by_the_number_of_tags(self):
        broad = story("Valuation and funding", ["Market-Valuations", "Venture-&-M&A"])
        narrow = story("A new bill", ["Legislation-&-Policy"])

        self.assertEqual(score_story(broad), 2)
        self.assertEqual(score_story(narrow), 1)
        self.assertEqual(select_stories([narrow, broad]), [
            {
                **broad,
                "selection_score": 2,
                "selection_reason": "Matched: Market-Valuations, Venture-&-M&A.",
            },
            {
                **narrow,
                "selection_score": 1,
                "selection_reason": "Matched: Legislation-&-Policy.",
            },
        ])

    def test_untagged_story_never_displaces_a_tagged_story(self):
        stories = [story("Aside", [])] + [
            story(f"Policy {index}", ["Legislation-&-Policy"]) for index in range(1, 6)
        ]

        selected = select_stories(stories)

        self.assertEqual(
            [item["headline"] for item in selected],
            ["Policy 1", "Policy 2", "Policy 3", "Policy 4", "Policy 5"],
        )
        self.assertNotIn("Aside", [item["headline"] for item in selected])

    def test_untagged_story_fills_one_unused_slot(self):
        selected = select_stories([
            story("Policy", ["Legislation-&-Policy"]),
            story("Aside", []),
        ])

        self.assertEqual([item["headline"] for item in selected], ["Policy", "Aside"])
        self.assertEqual(selected[1]["selection_score"], 0)
        self.assertEqual(selected[1]["selection_reason"], "No tag matched.")

    def test_each_present_tag_keeps_its_highest_story(self):
        stories = [
            story("Market one", ["Market-Valuations"]),
            story("Market two", ["Market-Valuations"]),
            story("Market three", ["Market-Valuations"]),
            story("Market four", ["Market-Valuations"]),
            story("Market five", ["Market-Valuations"]),
            story("Market six", ["Market-Valuations"]),
            story("Bill", ["Legislation-&-Policy"]),
            story("Model", ["Foundation-Models"]),
            story("Later market", ["Market-Valuations"]),
            story("Aside", []),
            story("Another aside", []),
        ]

        selected = select_stories(stories)
        headlines = [item["headline"] for item in selected]

        self.assertEqual(
            headlines,
            [
                "Market one",
                "Market two",
                "Market three",
                "Market four",
                "Market five",
                "Bill",
                "Model",
            ],
        )
        bill = next(item for item in selected if item["headline"] == "Bill")
        self.assertEqual(bill["selection_score"], 1)
        self.assertEqual(bill["selection_reason"], "Matched: Legislation-&-Policy.")
        self.assertNotIn("Market six", headlines)
        self.assertNotIn("Aside", headlines)
        self.assertNotIn("Another aside", headlines)

    def test_a_missing_tag_adds_nothing(self):
        selected = select_stories([
            story("Bill", ["Legislation-&-Policy"]),
            story("Funding", ["Venture-&-M&A", "Market-Valuations"]),
        ])

        self.assertEqual(
            [item["headline"] for item in selected],
            ["Funding", "Bill"],
        )


if __name__ == "__main__":
    unittest.main()
