"""Assign V2.5 tags from a story headline and RSS description.

This module does not change the raw stories. It returns a new enriched copy.
"""

import re

from config_loader import load_config


_CONFIG = load_config()
_TAXONOMY = _CONFIG["taxonomy"]
TAG_LABELS = tuple(_TAXONOMY)
TAG_KEYWORDS = {
    label: tuple(keywords) for label, keywords in _TAXONOMY.items()
}


def _tag_weights_from_config(config: dict) -> dict[str, int]:
    """Higher integer wins. Missing labels fall back to YAML order (earlier = higher)."""
    raw = config.get("tag_weights")
    n = len(TAG_LABELS)
    fallback = {label: n - index for index, label in enumerate(TAG_LABELS)}
    if not isinstance(raw, dict) or not raw:
        return fallback
    weights = dict(fallback)
    for label in TAG_LABELS:
        value = raw.get(label)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        weights[label] = int(value)
    return weights


TAG_WEIGHTS = _tag_weights_from_config(_CONFIG)


def primary_tag(tags: list[str]) -> str | None:
    """Return the highest-weight taxonomy tag, or None when none match."""
    assigned = [tag for tag in tags if tag in TAG_LABELS]
    if not assigned:
        return None
    return max(
        assigned,
        key=lambda tag: (TAG_WEIGHTS.get(tag, 0), -TAG_LABELS.index(tag)),
    )


def contains_keyword(text: str, keyword: str) -> bool:
    """Match a keyword as a word or phrase, including the unhyphenated form of lay-offs."""
    if keyword == "lay-offs":
        pattern = r"\blay[-\s]?offs\b"
    else:
        pattern = rf"\b{re.escape(keyword)}\b"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def tags_for_text(headline: str, description: str = "") -> list[str]:
    """Return every V2.5 label whose keywords appear in the headline or description."""
    text = f"{headline}\n{description}"
    return [
        label
        for label in TAG_LABELS
        if any(contains_keyword(text, keyword) for keyword in TAG_KEYWORDS[label])
    ]


def tags_for_headline(headline: str) -> list[str]:
    """Tag a headline alone. Descriptions are included by ``tags_for_text``."""
    return tags_for_text(headline)


def enrich_story(story: dict[str, str]) -> dict[str, object]:
    """Return a copy of a raw story with its derived ``tags`` list."""
    return {
        **story,
        "tags": tags_for_text(
            str(story.get("headline") or ""),
            str(story.get("description") or ""),
        ),
    }


def has_all_topics(story: dict[str, object], required_topics: set[str]) -> bool:
    """Return whether a tagged story has every requested tag."""
    return required_topics.issubset(set(story.get("tags") or []))
