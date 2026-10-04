"""Select the most consequential stories from an enriched run.

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


def select_stories(
    stories: list[dict[str, object]], maximum: int = MAX_STORIES
) -> list[dict[str, object]]:
    """Select up to ``maximum`` consequential stories without promoting misc items.

    Equal scores keep their original feed order. A misc story is considered only
    when there are fewer consequential stories than available slots.
    """
    consequential = [story for story in stories if story["topics"] != ["misc"]]
    ranked_stories = sorted(consequential, key=score_story, reverse=True)
    selected = ranked_stories[:maximum]

    if len(selected) < maximum:
        misc_story = next((story for story in stories if story["topics"] == ["misc"]), None)
        if misc_story:
            selected.append(misc_story)

    return [
        {
            **story,
            "selection_score": score_story(story),
            "selection_reason": selection_reason(story),
        }
        for story in selected
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
        description="Select up to five stories from an enriched story run."
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
