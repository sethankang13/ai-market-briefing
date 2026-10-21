"""Run the daily Loop: AI Market Briefing from collection through Markdown.

Run from the project folder:
    python3 src/run_briefing.py
    python3 src/run_briefing.py --mock
"""

import argparse
import json
import sys
from pathlib import Path

import collect_stories
import db
import enrich_stories
import fetch_market
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


def market_step() -> dict:
    """Fetch Fed Funds and index quotes without inventing numbers."""
    return fetch_market.fetch_market_snapshot()


def summarize_step(selected_path: Path, mock: bool = False) -> Path:
    """Add Why It Matters text to the selected run this command just wrote."""
    selected_run = summarize_stories.load_selected_run(selected_path)
    return summarize_stories.save_summarized_run(selected_run, selected_path, mock=mock)


def attach_market(summarized_path: Path, snapshot: dict) -> dict:
    """Store the market snapshot on the summarized run so the brief can render it."""
    payload = json.loads(summarized_path.read_text(encoding="utf-8"))
    payload["market_snapshot"] = snapshot
    summarized_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def write_brief_step(summarized_path: Path) -> Path:
    """Render the summarized run this command just wrote."""
    summarized_run = write_brief.load_selected_run(summarized_path)
    return write_brief.save_brief(summarized_run, summarized_path)


def persist_step(summarized_run: dict, snapshot: dict) -> Path:
    """Append this run's stories to the gitignored Loop history database."""
    inserted = db.append_stories(summarized_run.get("stories") or [], snapshot)
    print(f"Appended {inserted} stories to {db.DEFAULT_DB_PATH}")
    return db.DEFAULT_DB_PATH


def _run(step: str, action):
    """Run one step, or stop the pipeline with that step's name."""
    try:
        return action()
    except StepFailed:
        raise
    except Exception as error:
        raise StepFailed(step, error) from error


def run_briefing(mock: bool = False) -> Path:
    """Collect, enrich, select, snapshot markets, summarize, write, and store.

    ``mock`` still collects the RSS feeds, but writes offline mock copy and
    does not call Gemini or OpenAI.
    """
    if not mock:
        summarize_stories.load_project_env()
    print("Loop: AI Market Briefing")
    raw_path = _run("collect", collect_step)
    print(f"Collected stories saved to {raw_path}")
    enriched_path = _run("enrich", lambda: enrich_step(raw_path))
    print(f"Enriched stories saved to {enriched_path}")
    selected_path = _run("select", lambda: select_step(enriched_path))
    print(f"Selected stories saved to {selected_path}")
    snapshot = _run("market", market_step)
    summarized_path = _run(
        "summarize", lambda: summarize_step(selected_path, mock=mock)
    )
    print(f"Summarized stories saved to {summarized_path}")
    summarized_run = _run(
        "market_attach", lambda: attach_market(summarized_path, snapshot)
    )
    brief_path = _run("write_brief", lambda: write_brief_step(summarized_path))
    print(f"Saved briefing to {brief_path}")
    _run("persist", lambda: persist_step(summarized_run, snapshot))
    return brief_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Collect, tag, select, and write the daily Loop briefing."
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Write offline mock summaries and do not call Gemini or OpenAI.",
    )
    args = parser.parse_args(argv)
    try:
        run_briefing(mock=args.mock)
    except StepFailed as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
