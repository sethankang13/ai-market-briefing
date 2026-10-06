"""Run the daily briefing from collection through the Markdown file.

Run from the project folder:
    python3 src/run_briefing.py
"""

import sys
from pathlib import Path

import collect_stories
import enrich_stories
import select_stories
import summarize_stories
import write_brief


class StepFailed(Exception):
    """One pipeline step raised; later steps should not run."""

    def __init__(self, step: str, error: Exception):
        self.step = step
        self.error = error
        super().__init__(f"{step} failed: {error}")


def collect_step() -> Path:
    """Collect the public feeds and save today's raw run."""
    stories, failed_sources = collect_stories.collect_stories()
    return collect_stories.save_run(stories, failed_sources)


def enrich_step(raw_path: Path) -> Path:
    """Tag the raw run this command just collected."""
    raw_run = enrich_stories.load_raw_run(raw_path)
    return enrich_stories.save_enriched_run(raw_run, raw_path)


def select_step(enriched_path: Path) -> Path:
    """Select stories from the enriched run this command just wrote."""
    enriched_run = select_stories.load_enriched_run(enriched_path)
    return select_stories.save_selected_run(enriched_run, enriched_path)


def summarize_step(selected_path: Path) -> Path:
    """Add Why It Matters text to the selected run this command just wrote."""
    selected_run = summarize_stories.load_selected_run(selected_path)
    return summarize_stories.save_summarized_run(selected_run, selected_path)


def write_brief_step(summarized_path: Path) -> Path:
    """Render the summarized run this command just wrote."""
    summarized_run = write_brief.load_selected_run(summarized_path)
    return write_brief.save_brief(summarized_run, summarized_path)


def _run(step: str, action):
    """Run one step, or stop the pipeline with that step's name."""
    try:
        return action()
    except StepFailed:
        raise
    except Exception as error:
        raise StepFailed(step, error) from error


def run_briefing() -> Path:
    """Collect, enrich, select, summarize, and write a brief. Stop on the first failure."""
    raw_path = _run("collect", collect_step)
    print(f"Collected stories saved to {raw_path}")
    enriched_path = _run("enrich", lambda: enrich_step(raw_path))
    print(f"Enriched stories saved to {enriched_path}")
    selected_path = _run("select", lambda: select_step(enriched_path))
    print(f"Selected stories saved to {selected_path}")
    summarized_path = _run("summarize", lambda: summarize_step(selected_path))
    print(f"Summarized stories saved to {summarized_path}")
    brief_path = _run("write_brief", lambda: write_brief_step(summarized_path))
    print(f"Saved briefing to {brief_path}")
    return brief_path


def main() -> None:
    try:
        run_briefing()
    except StepFailed as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
