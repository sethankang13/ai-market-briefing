"""Assign transparent topic tags to story headlines.

This module does not change the raw stories. It returns a new enriched copy.
"""

import re


TOPIC_KEYWORDS = {
    "oil": ("oil", "crude"),
    "energy": ("energy", "solar", "nuclear"),
    "technology": ("technology", "tech", "artificial intelligence", "ai"),
    "policy": (
        "federal reserve",
        "fed",
        "interest rate",
        "interest rates",
        "inflation",
        "tariff",
        "tariffs",
        "tax policy",
        "tax policies",
        "tax rate",
        "tax rates",
        "tax rise",
        "tax rises",
        "tax increase",
        "tax increases",
        "tax cut",
        "tax cuts",
        "new tax",
        "new taxes",
        "higher tax",
        "higher taxes",
        "trade restriction",
        "trade restrictions",
        "sanction",
        "sanctions",
        "government spending",
        "budget",
    ),
}


def contains_keyword(headline: str, keyword: str) -> bool:
    """Match whole words so, for example, 'oil' does not match 'boil'."""
    pattern = rf"\b{re.escape(keyword)}\b"
    return bool(re.search(pattern, headline, flags=re.IGNORECASE))


def tags_for_headline(headline: str) -> list[str]:
    """Return every topic whose keywords appear in a headline."""
    tags = [
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(contains_keyword(headline, keyword) for keyword in keywords)
    ]

    # Oil is one part of the broader energy sector.
    if "oil" in tags and "energy" not in tags:
        tags.insert(tags.index("oil") + 1, "energy")

    return tags or ["misc"]


def enrich_story(story: dict[str, str]) -> dict[str, object]:
    """Return a copy of a raw story with its derived topic tags."""
    return {**story, "topics": tags_for_headline(story["headline"])}


def has_all_topics(story: dict[str, object], required_topics: set[str]) -> bool:
    """Return whether a tagged story has every requested topic."""
    return required_topics.issubset(set(story["topics"]))
