"""Select consequential stories from an enriched run, with one story per tag.

Run from the project folder:
    python3 src/select_stories.py
"""

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENRICHED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "enriched"
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
TOPIC_SCORES = {
    "oil": 5,
    "policy": 4,
    "energy": 3,
    "technology": 2,
    "misc": 0,
}
TAG_ORDER = ("policy", "oil", "energy", "technology", "misc")
MAX_STORIES = 5


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
    """Load one enriched run and make sure its stories have topic lists."""
    enriched_run = json.loads(input_path.read_text(encoding="utf-8"))
    stories = enriched_run.get("stories") if isinstance(enriched_run, dict) else None
    if not isinstance(stories, list) or any(
        not isinstance(story.get("topics"), list) for story in stories
    ):
        raise ValueError(f"{input_path} does not contain stories with topic lists.")
    return enriched_run


def score_story(story: dict[str, object]) -> int:
    """Score one story only from its transparent, previously derived topics."""
    return sum(TOPIC_SCORES.get(topic, 0) for topic in story["topics"])


def selection_reason(story: dict[str, object]) -> str:
    """Give the reader a short explanation of why this story ranked here."""
    ranked_topics = [topic for topic in story["topics"] if topic != "misc"]
    if not ranked_topics:
        return "Interesting aside; no current market-topic rule matched."
    return "Matched: " + ", ".join(ranked_topics) + "."


def _ranked_indexes(stories: list[dict[str, object]], indexes: list[int]) -> list[int]:
    """Order indexes by score, keeping the original feed order when scores tie."""
    return sorted(indexes, key=lambda index: (-score_story(stories[index]), index))


def _is_misc(story: dict[str, object]) -> bool:
    return story["topics"] == ["misc"]


def select_stories(
    stories: list[dict[str, object]], maximum: int = MAX_STORIES
) -> list[dict[str, object]]:
    """Select the top stories by score, plus the best story for each tag present.

    The top ``maximum`` slots still prefer tagged stories. A misc story fills a
    leftover slot and can also represent the misc tag, but the whole set keeps
    at most one misc story. Equal scores keep their original feed order.
    """
    consequential = [
        index for index, story in enumerate(stories) if not _is_misc(story)
    ]
    selected_indexes = _ranked_indexes(stories, consequential)[:maximum]

    if len(selected_indexes) < maximum:
        misc_index = next(
            (index for index, story in enumerate(stories) if _is_misc(story)),
            None,
        )
        if misc_index is not None:
            selected_indexes.append(misc_index)

    selected = set(selected_indexes)
    for tag in TAG_ORDER:
        tagged = [
            index for index, story in enumerate(stories) if tag in story["topics"]
        ]
        if not tagged:
            continue
        best_index = _ranked_indexes(stories, tagged)[0]
        if tag == "misc" and any(_is_misc(stories[index]) for index in selected):
            continue
        selected.add(best_index)

    misc_indexes = [index for index in selected if _is_misc(stories[index])]
    if len(misc_indexes) > 1:
        kept_misc = _ranked_indexes(stories, misc_indexes)[0]
        selected = {
            index for index in selected if not _is_misc(stories[index]) or index == kept_misc
        }

    return [
        {
            **stories[index],
            "selection_score": score_story(stories[index]),
            "selection_reason": selection_reason(stories[index]),
        }
        for index in _ranked_indexes(stories, list(selected))
    ]


def save_selected_run(enriched_run: dict[str, object], input_path: Path) -> Path:
    """Save selected copies separately from the enriched collection."""
    SELECTED_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = SELECTED_DATA_DIRECTORY / input_path.name
    output = {
        "enriched_run": input_path.name,
        "failed_sources": enriched_run.get("failed_sources", []),
        "stories": select_stories(enriched_run["stories"]),
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
    print(f"Selected {len(select_stories(enriched_run['stories']))} stories.")
    print(f"Saved selected data to {saved_file}")
