"""Run the daily Loop: AI Market Briefing from collection through Markdown.

Run from the project folder:
    python3 src/run_briefing.py
    python3 src/run_briefing.py --mock
    python3 src/run_briefing.py --mock --open
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import collect_stories
import db
import enrich_stories
import fetch_market
import select_stories
import summarize_stories
import write_brief

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENRICHED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "enriched"


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


def market_step(mock: bool = False) -> dict:
    """Fetch Fed Funds and index quotes, or use a realistic offline snapshot."""
    if mock:
        return fetch_market.mock_market_snapshot()
    return fetch_market.fetch_market_snapshot()


def summarize_step(selected_path: Path, mock: bool = False) -> Path:
    """Write one headline-based macro report for the selected run."""
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


def _story_url(story: dict) -> str:
    return str(story.get("link") or story.get("url") or "").strip()


def stories_for_loop_db(summarized_run: dict, enriched_run: dict | None = None) -> list[dict]:
    """Every collected RSS item, with ``is_selected`` for brief picks."""
    selected = summarized_run.get("stories") if isinstance(summarized_run, dict) else None
    selected_stories = selected if isinstance(selected, list) else []
    selected_by_url = {
        url: story
        for story in selected_stories
        if (url := _story_url(story))
    }
    collected = []
    if isinstance(enriched_run, dict) and isinstance(enriched_run.get("stories"), list):
        collected = enriched_run["stories"]
    if not collected:
        rows = []
        for story in selected_stories:
            item = dict(story)
            item["is_selected"] = 1
            rows.append(item)
        return rows
    rows = []
    for story in collected:
        if not isinstance(story, dict):
            continue
        item = dict(story)
        url = _story_url(item)
        overlay = selected_by_url.get(url)
        if overlay:
            if overlay.get("ai_summary"):
                item["ai_summary"] = overlay["ai_summary"]
            item["is_selected"] = 1
        else:
            item["is_selected"] = 0
        rows.append(item)
    return rows


def load_enriched_for_persist(summarized_run: dict) -> dict | None:
    """Load ``data/enriched/YYYY-MM-DD.json`` named by the summarized run."""
    name = None
    if isinstance(summarized_run, dict):
        name = summarized_run.get("selected_run") or summarized_run.get("enriched_run")
    if not isinstance(name, str) or not name.strip():
        return None
    path = ENRICHED_DATA_DIRECTORY / Path(name).name
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def persist_step(summarized_run: dict, snapshot: dict) -> Path:
    """Store every collected RSS story; mark brief picks with ``is_selected``."""
    macro = summarized_run.get("macro_report")
    stories = stories_for_loop_db(summarized_run, load_enriched_for_persist(summarized_run))
    inserted = db.append_stories(
        stories,
        snapshot,
        macro_report=macro if isinstance(macro, str) else None,
    )
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


def snapshot_status_line(snapshot: dict | None) -> str:
    """One-line Market Snapshot status: Fed, S&P, Nasdaq, Dow."""
    data = snapshot if isinstance(snapshot, dict) else None
    fed = data.get("fed_funds") if isinstance(data, dict) and isinstance(data.get("fed_funds"), dict) else {}
    indexes = data.get("indexes") if isinstance(data, dict) and isinstance(data.get("indexes"), dict) else {}
    parts = [f"Fed Funds: {fetch_market.format_fed_funds(fed)}"]
    for symbol, label in fetch_market.INDEXES:
        entry = indexes.get(symbol) if isinstance(indexes.get(symbol), dict) else {}
        parts.append(f"{label}: {fetch_market.format_index(entry)}")
    return "Market Snapshot: " + "; ".join(parts)


def completion_banner(brief_path: Path, summarized_run: dict | None) -> str:
    """Deterministic end-of-run summary for mock and live pipelines."""
    payload = summarized_run if isinstance(summarized_run, dict) else {}
    stories = payload.get("stories")
    count = len(stories) if isinstance(stories, list) else 0
    snapshot = payload.get("market_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = None
    lines = [
        "Loop complete",
        f"Output: {brief_path}",
        f"Stories selected: {count}",
        snapshot_status_line(snapshot),
    ]
    failed = payload.get("failed_sources")
    if isinstance(failed, list) and failed:
        lines.append("failed_sources: " + ", ".join(str(source) for source in failed))
    return "\n".join(lines)


def open_briefing_file(brief_path: Path) -> None:
    """Open the briefing with macOS ``open``. No-op on other platforms.

    ``subprocess.run`` is used instead of ``os.system`` so the path is not
    interpolated into a shell string.
    """
    if sys.platform != "darwin":
        print(
            f"--open is supported on macOS only; briefing remains at {brief_path}"
        )
        return
    try:
        subprocess.run(["open", str(brief_path)], check=False)
    except OSError as error:
        print(f"Could not open {brief_path}: {error}")


def run_briefing(mock: bool = False, open_after: bool = False) -> Path:
    """Collect, enrich, select, snapshot markets, summarize, write, and store.

    ``mock`` still collects the RSS feeds, but writes offline mock macro
    sections and does not call Gemini or OpenAI.
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
    snapshot = _run("market", lambda: market_step(mock=mock))
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
    print(completion_banner(brief_path, summarized_run))
    if open_after:
        open_briefing_file(brief_path)
    return brief_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Collect, tag, select, and write the daily Loop briefing."
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Write offline mock macro sections and do not call Gemini or OpenAI.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_after",
        help="After writing, open briefs/YYYY-MM-DD.md (macOS `open`; no-op elsewhere).",
    )
    args = parser.parse_args(argv)
    try:
        run_briefing(mock=args.mock, open_after=args.open_after)
    except StepFailed as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
