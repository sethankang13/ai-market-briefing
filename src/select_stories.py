"""Select consequential stories from an enriched run, with one story per tag.

Audited against the six Loop tags: US Politics, Market Valuations,
Labor & Economy, Geopolitics & Trade, Tech & Innovation, Venture & M&A.

Run from the project folder:
    python3 src/select_stories.py
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from config_loader import load_config
from tag_stories import TAG_LABELS

_CONFIG = load_config()
LOOP_TAGS = TAG_LABELS
RECENCY_WINDOW = timedelta(hours=int(_CONFIG["pipeline"]["recency_cutoff_hours"]))


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENRICHED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "enriched"
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
MAX_STORIES = int(_CONFIG["pipeline"]["top_selected_stories"])


def latest_enriched_run(enriched_data_directory: Path = ENRICHED_DATA_DIRECTORY) -> Path:
    """Return the newest enriched run, or explain why one cannot be found."""
    enriched_runs = sorted(enriched_data_directory.glob("*.json"))
    if not enriched_runs:
        raise FileNotFoundError(
            f"No enriched story runs found in {enriched_data_directory}. "
            "Run enrich_stories.py first."
        )
    return enriched_runs[-1]


def load_enriched_run(input_path: Path) -> dict[str, object]:
    """Load one enriched run and make sure its stories have tag lists."""
    enriched_run = json.loads(input_path.read_text(encoding="utf-8"))
    stories = enriched_run.get("stories") if isinstance(enriched_run, dict) else None
    if not isinstance(stories, list) or any(
        not isinstance(story.get("tags"), list) for story in stories
    ):
        raise ValueError(f"{input_path} does not contain stories with tag lists.")
    return enriched_run


def story_tags(story: dict[str, object]) -> list[str]:
    """Return the story's tags, treating a missing list as untagged."""
    tags = story.get("tags")
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, str)]


def score_story(story: dict[str, object]) -> int:
    """Score one story as the count of its real tags. Ties keep feed order."""
    return sum(1 for tag in story_tags(story) if tag != "misc")


def selection_reason(story: dict[str, object]) -> str:
    """Give the reader a short explanation of why this story ranked here."""
    matched = [tag for tag in story_tags(story) if tag != "misc"]
    if not matched:
        return "No tag matched."
    return "Matched: " + ", ".join(matched) + "."


def _ranked_indexes(stories: list[dict[str, object]], indexes: list[int]) -> list[int]:
    """Order indexes by score, keeping the original feed order when scores tie."""
    return sorted(indexes, key=lambda index: (-score_story(stories[index]), index))


def _is_untagged(story: dict[str, object]) -> bool:
    tags = [tag for tag in story_tags(story) if tag != "misc"]
    return not tags


def _published_on_day(story: dict[str, object], run_day) -> bool:
    """True when RSS pubDate falls on the run's UTC calendar day."""
    published = parse_published_at(story.get("published_at"))
    if published is None:
        return False
    return published.date() == run_day


def _rank_today_first(
    stories: list[dict[str, object]], indexes: list[int], run_day
) -> list[int]:
    """Prefer same-calendar-day items, then fall back to the 48-hour pool."""
    today = [index for index in indexes if _published_on_day(stories[index], run_day)]
    rest = [index for index in indexes if index not in set(today)]
    if today:
        return _ranked_indexes(stories, today) + _ranked_indexes(stories, rest)
    return _ranked_indexes(stories, indexes)


def select_stories(
    stories: list[dict[str, object]],
    maximum: int = MAX_STORIES,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Select the top stories by score, plus the best story for each tag present.

    Same-day RSS items beat older items still inside the 48-hour collect window.
    The top ``maximum`` slots still prefer tagged stories. An untagged story fills
    a leftover slot only, and the whole set keeps at most one untagged story.
    Each real tag is worth one point. Equal scores keep their original feed order.
    """
    run_day = (_as_utc(now) if now is not None else datetime.now(timezone.utc)).date()
    consequential = [
        index for index, story in enumerate(stories) if not _is_untagged(story)
    ]
    today_consequential = [
        index for index in consequential if _published_on_day(stories[index], run_day)
    ]
    pool = today_consequential if today_consequential else consequential
    selected_indexes = _ranked_indexes(stories, pool)[:maximum]

    if len(selected_indexes) < maximum:
        untagged_index = next(
            (index for index, story in enumerate(stories) if _is_untagged(story)),
            None,
        )
        if untagged_index is not None:
            selected_indexes.append(untagged_index)

    selected = set(selected_indexes)
    for tag in TAG_LABELS:
        tagged = [index for index, story in enumerate(stories) if tag in story_tags(story)]
        if not tagged:
            continue
        best_index = _rank_today_first(stories, tagged, run_day)[0]
        selected.add(best_index)

    untagged_indexes = [index for index in selected if _is_untagged(stories[index])]
    if len(untagged_indexes) > 1:
        kept = _ranked_indexes(stories, untagged_indexes)[0]
        selected = {
            index for index in selected if not _is_untagged(stories[index]) or index == kept
        }

    return [
        {
            **stories[index],
            "selection_score": score_story(stories[index]),
            "selection_reason": selection_reason(stories[index]),
        }
        for index in _rank_today_first(stories, list(selected), run_day)
    ]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_published_at(value: object) -> datetime | None:
    """Parse RSS pubDate / ISO timestamps for recency scoring."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return _as_utc(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        pass
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return _as_utc(datetime.fromisoformat(iso))
    except ValueError:
        return None


def recency_score(story: dict[str, object], now: datetime | None = None) -> float:
    """Score 1.0 at publish time down to 0.0 at 48 hours. Undated stories score 0.5."""
    published = parse_published_at(story.get("published_at"))
    if published is None:
        return 0.5
    run_at = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    age = run_at - published
    if age <= timedelta(0):
        return 1.0
    if age >= RECENCY_WINDOW:
        return 0.0
    remaining = RECENCY_WINDOW - age
    return remaining / RECENCY_WINDOW


def tag_density(stories: list[dict[str, object]]) -> dict[str, object]:
    """Count how often each of the six Loop tags appears."""
    counts = {label: 0 for label in LOOP_TAGS}
    tagged_stories = 0
    total_tags = 0
    for story in stories:
        matched = [tag for tag in story_tags(story) if tag in counts]
        if matched:
            tagged_stories += 1
        for tag in matched:
            counts[tag] += 1
            total_tags += 1
    average = (total_tags / len(stories)) if stories else 0.0
    return {
        "per_tag": counts,
        "tagged_stories": tagged_stories,
        "average_tags_per_story": average,
    }


def selection_diagnostics(
    stories: list[dict[str, object]], now: datetime | None = None
) -> dict[str, object]:
    """Summarize evaluation size, tag density, and mean recency score."""
    density = tag_density(stories)
    scores = [recency_score(story, now=now) for story in stories]
    mean_recency = sum(scores) / len(scores) if scores else 0.0
    return {
        "stories_evaluated": len(stories),
        "tag_density": density,
        "recency_score": mean_recency,
    }


def print_selection_diagnostics(
    stories: list[dict[str, object]], now: datetime | None = None
) -> dict[str, object]:
    """Print stories evaluated, tag density, and recency score."""
    diagnostics = selection_diagnostics(stories, now=now)
    density = diagnostics["tag_density"]
    per_tag = ", ".join(
        f"{label}={count}" for label, count in density["per_tag"].items()
    )
    print(f"Stories evaluated: {diagnostics['stories_evaluated']}")
    print(
        "Tag density: "
        f"{density['average_tags_per_story']:.2f} tags/story "
        f"({density['tagged_stories']} tagged); {per_tag}"
    )
    print(f"Recency score: {diagnostics['recency_score']:.2f}")
    return diagnostics


def save_selected_run(enriched_run: dict[str, object], input_path: Path) -> Path:
    """Save selected copies separately from the enriched collection."""
    SELECTED_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stories = enriched_run["stories"]
    print_selection_diagnostics(stories)
    output_path = SELECTED_DATA_DIRECTORY / input_path.name
    output = {
        "enriched_run": input_path.name,
        "failed_sources": enriched_run.get("failed_sources", []),
        "stories": select_stories(stories, now=datetime.now(timezone.utc)),
    }
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select top stories plus the best story for each tag present."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="Enriched JSON file to select from. Defaults to the latest data/enriched file.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_enriched_run()
    enriched_run = load_enriched_run(input_file)
    saved_file = save_selected_run(enriched_run, input_file)
    print(f"Loop: selected {len(select_stories(enriched_run['stories']))} stories.")
    print(f"Saved selected data to {saved_file}")
