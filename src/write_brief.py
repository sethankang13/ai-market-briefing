"""Render a readable local briefing from a summarized or selected story run.

Run from the project folder:
    python3 src/write_brief.py
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


from tag_stories import TAG_LABELS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARIZED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "summarized"
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
BRIEFS_DIRECTORY = PROJECT_ROOT / "briefs"
SECTION_ORDER = TAG_LABELS + ("Other",)


def latest_summarized_run(summarized_data_directory=None):
    """Return the newest summarized run, or None when none exist."""
    directory = summarized_data_directory or SUMMARIZED_DATA_DIRECTORY
    summarized_runs = sorted(directory.glob("*.json"))
    return summarized_runs[-1] if summarized_runs else None


def latest_selected_run(selected_data_directory=None):
    """Return the newest selected run, or explain why one cannot be found."""
    directory = selected_data_directory or SELECTED_DATA_DIRECTORY
    selected_runs = sorted(directory.glob("*.json"))
    if not selected_runs:
        raise FileNotFoundError(
            f"No selected story runs found in {directory}. "
            "Run select_stories.py first."
        )
    return selected_runs[-1]


def latest_briefing_source(summarized_data_directory=None, selected_data_directory=None):
    """Prefer a summarized run; fall back to the latest selected run."""
    return latest_summarized_run(summarized_data_directory) or latest_selected_run(
        selected_data_directory
    )


def load_selected_run(input_path: Path) -> dict[str, object]:
    """Load one story run and make sure it has a story list."""
    selected_run = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(selected_run, dict) or not isinstance(selected_run.get("stories"), list):
        raise ValueError(f"{input_path} does not contain a 'stories' list.")
    return selected_run


def story_tags(story: dict[str, object]) -> list[str]:
    """Return assigned tags, ignoring a missing or non-list value."""
    tags = story.get("tags")
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, str) and tag]


def section_for_story(story: dict[str, object]) -> str:
    """Choose one section from the first assigned tag in the V2.5 label order."""
    tags = story_tags(story)
    for label in TAG_LABELS:
        if label in tags:
            return label
    return "Other"


def tags_line(story: dict[str, object]) -> str:
    """Render the italic tag line under the story title."""
    hashes = " ".join(f"#{tag}" for tag in story_tags(story))
    if hashes:
        return f"  *Tags: {hashes}*  "
    return "  *Tags:*  "


def display_date(date_stem: str) -> str:
    """Turn a date-based filename into a friendly briefing date."""
    return datetime.strptime(date_stem, "%Y-%m-%d").strftime("%B %-d, %Y")


def why_it_matters(story: dict[str, object]) -> str:
    """Use the stored AI summary, or a pending placeholder."""
    summary = story.get("ai_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return f"[AI Summary Pending: {story['headline']}]"


def render_story(story: dict[str, object]) -> str:
    """Lead with the AI headline, then the source headline, tags, and why it matters."""
    source_link = f"[{story['headline']}]({story['link']})"
    why = f"  Why It Matters: {why_it_matters(story)}"
    body = f"  {source_link}  \n{tags_line(story)}\n{why}"
    ai_headline = story.get("ai_headline")
    if isinstance(ai_headline, str) and ai_headline.strip():
        return f"- {ai_headline.strip()}  \n{body}"
    return f"- {source_link}  \n{tags_line(story)}\n{why}"


def render_brief(selected_run: dict[str, object], date_stem: str) -> str:
    """Render the selected stories as a concise, topic-organized Markdown brief."""
    sections = {section: [] for section in SECTION_ORDER}
    for story in selected_run["stories"]:
        sections[section_for_story(story)].append(story)

    lines = [
        f"# AI Market Briefing — {display_date(date_stem)}",
        "",
        "Selected public reporting, organized by topic. Links lead to the original source.",
    ]
    for section in SECTION_ORDER:
        if sections[section]:
            lines.extend(["", f"## {section}", ""])
            lines.extend(render_story(story) for story in sections[section])

    return "\n".join(lines) + "\n"


def save_brief(selected_run: dict[str, object], input_path: Path) -> Path:
    """Save a Markdown briefing beside other generated briefings."""
    BRIEFS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = BRIEFS_DIRECTORY / f"{input_path.stem}.md"
    output_path.write_text(
        render_brief(selected_run, input_path.stem), encoding="utf-8"
    )
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a topic-organized local market briefing."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="Summarized or selected JSON file to render. Defaults to summarized, then selected.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_briefing_source()
    selected_run = load_selected_run(input_file)
    saved_file = save_brief(selected_run, input_file)
    print(f"Wrote {len(selected_run['stories'])} stories.")
    print(f"Saved briefing to {saved_file}")
