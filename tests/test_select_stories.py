import io
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from select_stories import (
    LOOP_TAGS,
    print_selection_diagnostics,
    recency_score,
    score_story,
    select_stories,
)
from tag_stories import TAG_LABELS


def story(headline: str, tags: list[str]) -> dict[str, object]:
    return {"headline": headline, "tags": tags}


class SelectStoriesTests(unittest.TestCase):
    def test_selection_uses_the_six_loop_tags(self):
        self.assertEqual(LOOP_TAGS, TAG_LABELS)
        self.assertEqual(
            list(LOOP_TAGS),
            [
                "US Politics",
                "Market Valuations",
                "Labor & Economy",
                "Geopolitics & Trade",
                "Tech & Innovation",
                "Venture & M&A",
            ],
        )

    def test_stories_rank_by_the_number_of_tags(self):
        broad = story("Valuation and funding", ["Market Valuations", "Venture & M&A"])
        narrow = story("A new bill", ["US Politics"])

        self.assertEqual(score_story(broad), 2)
        self.assertEqual(score_story(narrow), 1)
        self.assertEqual(select_stories([narrow, broad]), [
            {
                **broad,
                "selection_score": 2,
                "selection_reason": "Matched: Market Valuations, Venture & M&A.",
            },
            {
                **narrow,
                "selection_score": 1,
                "selection_reason": "Matched: US Politics.",
            },
        ])

    def test_untagged_story_never_displaces_a_tagged_story(self):
        stories = [story("Aside", [])] + [
            story(f"Policy {index}", ["US Politics"]) for index in range(1, 6)
        ]

        selected = select_stories(stories)

        self.assertEqual(
            [item["headline"] for item in selected],
            ["Policy 1", "Policy 2", "Policy 3", "Policy 4", "Policy 5"],
        )
        self.assertNotIn("Aside", [item["headline"] for item in selected])

    def test_untagged_story_fills_one_unused_slot(self):
        selected = select_stories([
            story("Policy", ["US Politics"]),
            story("Aside", []),
        ])

        self.assertEqual([item["headline"] for item in selected], ["Policy", "Aside"])
        self.assertEqual(selected[1]["selection_score"], 0)
        self.assertEqual(selected[1]["selection_reason"], "No tag matched.")

    def test_each_present_tag_keeps_its_highest_story(self):
        stories = [
            story("Market one", ["Market Valuations"]),
            story("Market two", ["Market Valuations"]),
            story("Market three", ["Market Valuations"]),
            story("Market four", ["Market Valuations"]),
            story("Market five", ["Market Valuations"]),
            story("Market six", ["Market Valuations"]),
            story("Bill", ["US Politics"]),
            story("Model", ["Tech & Innovation"]),
            story("Later market", ["Market Valuations"]),
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
        self.assertEqual(bill["selection_reason"], "Matched: US Politics.")
        self.assertNotIn("Market six", headlines)
        self.assertNotIn("Aside", headlines)
        self.assertNotIn("Another aside", headlines)

    def test_same_day_stories_beat_older_48h_headlines(self):
        now = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
        selected = select_stories(
            [
                {
                    **story("Yesterday IPO", ["Market Valuations"]),
                    "published_at": "Fri, 23 Oct 2026 12:00:00 GMT",
                },
                {
                    **story("Today funding", ["Market Valuations"]),
                    "published_at": "Sat, 24 Oct 2026 09:00:00 GMT",
                },
            ],
            now=now,
        )
        self.assertEqual([item["headline"] for item in selected], ["Today funding"])

    def test_a_missing_tag_adds_nothing(self):
        selected = select_stories([
            story("Bill", ["US Politics"]),
            story("Funding", ["Venture & M&A", "Market Valuations"]),
        ])

        self.assertEqual(
            [item["headline"] for item in selected],
            ["Funding", "Bill"],
        )

    def test_diagnostics_print_evaluated_density_and_recency(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        stories = [
            {
                "headline": "Fresh policy",
                "tags": ["US Politics"],
                "published_at": "Tue, 06 Oct 2026 10:00:00 GMT",
            },
            {
                "headline": "Older market",
                "tags": ["Market Valuations", "Venture & M&A"],
                "published_at": "Mon, 05 Oct 2026 12:00:00 GMT",
            },
        ]
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            diagnostics = print_selection_diagnostics(stories, now=now)
        text = buffer.getvalue()
        self.assertIn("Stories evaluated: 2", text)
        self.assertIn("Tag density:", text)
        self.assertIn("Recency score:", text)
        self.assertEqual(diagnostics["stories_evaluated"], 2)
        self.assertEqual(diagnostics["tag_density"]["per_tag"]["US Politics"], 1)
        self.assertGreater(recency_score(stories[0], now=now), recency_score(stories[1], now=now))


if __name__ == "__main__":
    unittest.main()
