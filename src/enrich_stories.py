"""Create a tagged copy of a saved raw story run.

Run from the project folder:
    python3 src/enrich_stories.py

Optionally enrich one particular raw run:
    python3 src/enrich_stories.py data/raw/2026-09-20.json
"""

import argparse
import json
from pathlib import Path

from tag_stories import enrich_story


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIRECTORY = PROJECT_ROOT / "data" / "raw"
ENRICHED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "enriched"


def latest_raw_run(raw_data_directory: Path = RAW_DATA_DIRECTORY) -> Path:
    """Return the newest saved raw run, or explain why one cannot be found."""
    raw_runs = sorted(raw_data_directory.glob("*.json"))
    if not raw_runs:
        raise FileNotFoundError(
            f"No raw story runs found in {raw_data_directory}. "
            "Run collect_stories.py first."
        )
    return raw_runs[-1]


def load_raw_run(input_path: Path) -> dict[str, object]:
    """Load one raw run and make sure it has the expected story list."""
    raw_run = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw_run, dict) or not isinstance(raw_run.get("stories"), list):
        raise ValueError(f"{input_path} does not contain a 'stories' list.")
    return raw_run


def enrich_stories(stories: list[dict[str, str]]) -> list[dict[str, object]]:
    """Make an enriched copy of every raw story without changing the raw list."""
    return [enrich_story(story) for story in stories]


def save_enriched_run(raw_run: dict[str, object], input_path: Path) -> Path:
    """Save derived tags separately while retaining useful collection metadata."""
    ENRICHED_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = ENRICHED_DATA_DIRECTORY / input_path.name
    output = {
        "raw_run": input_path.name,
        "failed_sources": raw_run.get("failed_sources", []),
        "stories": enrich_stories(raw_run["stories"]),
    }
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add topic tags to a saved raw story run."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="Raw JSON file to enrich. Defaults to the latest file in data/raw.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_raw_run()
    raw_run = load_raw_run(input_file)
    saved_file = save_enriched_run(raw_run, input_file)
    print(f"Enriched {len(raw_run['stories'])} stories.")
    print(f"Saved enriched data to {saved_file}")
