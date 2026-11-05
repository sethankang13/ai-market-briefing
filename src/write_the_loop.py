"""Render a historical Loop report from data/loop.db.

Daily briefs use ``# Looping... (YYYY-MM-DD)``. Aggregated history uses
``# The Loop: Macro Summary (Last N Days)``. ``--synthesize`` prepends a
macro trajectory under that header from stored ``macro_report`` JSON.

Run from the project folder:
    python3 src/write_the_loop.py
    python3 src/write_the_loop.py --days 14 --tag "US Politics" --limit 15
    python3 src/write_the_loop.py --synthesize --mock --days 14
    python3 src/write_the_loop.py --open
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import db
import fetch_market
import summarize_stories
import write_brief
from config_loader import load_config, project_path


_CONFIG = load_config()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = project_path(_CONFIG["pipeline"]["output_dir"]) / "THE_LOOP.md"


TRAJECTORY_SYSTEM_PROMPT = (
    "You write Loop: AI Market Briefing's multi-week meta-synthesis from "
    "stored daily_summary and tag_notes JSON. Do not claim you read full "
    "articles. Do not invent facts that are not supported by the supplied "
    "daily summaries or tag notes. Label market-impact or causal language "
    "as interpretation. Return JSON only (no Markdown wrapper) with this "
    "shape:\n"
    '{"narrative_arcs": ["arc 1", "arc 2", "arc 3"], '
    '"signal_momentum": {"gaining": ["topic"], "fading": ["topic"]}, '
    '"pivot_points": ["shift 1"]}\n'
    "narrative_arcs: 3-4 persistent multi-week story arcs. "
    "signal_momentum: topics that are gaining versus fading. "
    "pivot_points: major shifts, policy turns, or market reversals."
)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a historical Loop macro summary from data/loop.db."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Include stories with published_date in the last N days (default 14).",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help='Keep rows whose stored tags contain this label, e.g. "US Politics".',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Maximum number of stories to include (default 15).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown output path (default briefs/THE_LOOP.md).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_after",
        help="After writing, open the file (macOS `open`; no-op elsewhere).",
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Prepend a macro trajectory from stored daily summaries and tag notes.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="With --synthesize, write a deterministic trajectory and skip Gemini.",
    )
    return parser.parse_args(argv)


def query_stories(
    days: int = 14,
    tag: str | None = None,
    limit: int = 15,
    db_path: Path | None = None,
) -> list[dict]:
    """Load recent rows with parameterized SQLite. Never interpolates user input."""
    modifier = f"-{int(days)} days"
    sql = (
        "SELECT id, published_date, headline, url, source, full_text, "
        "ai_summary, tags, market_snapshot_json FROM stories "
        "WHERE published_date >= date('now', ?)"
    )
    params: list[object] = [modifier]
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    sql += " ORDER BY published_date DESC, id DESC LIMIT ?"
    params.append(int(limit))

    path = Path(db_path) if db_path is not None else db.DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(db.SCHEMA)
        cursor = connection.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def row_as_story(row: dict) -> dict[str, object]:
    """Map a SQLite history row onto the daily brief story shape."""
    tags = row.get("tags")
    try:
        parsed = json.loads(tags) if isinstance(tags, str) else tags
    except json.JSONDecodeError:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []
    return {
        "headline": row.get("headline") or "(untitled)",
        "link": row.get("url") or "",
        "source": row.get("source") or "Unknown source",
        "published_at": row.get("published_date") or "",
        "tags": [tag for tag in parsed if isinstance(tag, str)],
        "ai_summary": row.get("ai_summary"),
    }


def _unique_snapshots(rows: list[dict]) -> list[dict]:
    snapshots = []
    seen: set[str] = set()
    for row in rows:
        raw = row.get("market_snapshot_json")
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        key = json.dumps(data, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        snapshots.append(data)
    return snapshots


def _format_snapshot_line(snapshot: dict) -> str:
    fed = snapshot.get("fed_funds") if isinstance(snapshot.get("fed_funds"), dict) else {}
    indexes = snapshot.get("indexes") if isinstance(snapshot.get("indexes"), dict) else {}
    parts = [f"Fed Funds {fetch_market.format_fed_funds(fed)}"]
    for symbol, label in fetch_market.INDEXES:
        entry = indexes.get(symbol) if isinstance(indexes.get(symbol), dict) else {}
        parts.append(f"{label} {fetch_market.format_index(entry)}")
    fetched = snapshot.get("fetched_at")
    prefix = f"{fetched}: " if isinstance(fetched, str) and fetched.strip() else ""
    return prefix + "; ".join(parts)


def _fed_funds_trend(snapshots: list[dict]) -> str | None:
    rates = []
    for snapshot in snapshots:
        fed = snapshot.get("fed_funds")
        if isinstance(fed, dict) and fed.get("status") == "ok":
            rate = fed.get("rate")
            if isinstance(rate, (int, float)):
                rates.append(float(rate))
    if len(rates) < 2:
        return None
    first, last = rates[0], rates[-1]
    if first == last:
        return f"Fed Funds was {first:.2f}% on every stored snapshot that included a rate."
    return f"Fed Funds across stored runs: {first:.2f}% → {last:.2f}%."


def render_market_trends(rows: list[dict]) -> str:
    """Summarize stored snapshots only. Do not invent missing quotes."""
    lines = ["## Market Snapshot Trends", ""]
    snapshots = _unique_snapshots(rows)
    if not snapshots:
        lines.append(
            "No stored market snapshot history for this window; "
            "Loop cannot invent those numbers."
        )
        return "\n".join(lines) + "\n"
    lines.append("From stored briefing runs (not live quotes):")
    lines.append("")
    for snapshot in snapshots:
        lines.append(f"- {_format_snapshot_line(snapshot)}")
    trend = _fed_funds_trend(snapshots)
    if trend:
        lines.extend(["", trend])
    return "\n".join(lines) + "\n"


def render_the_loop(
    rows: list[dict],
    days: int = 14,
    tag: str | None = None,
) -> str:
    """Render stored stories as a historical Markdown report titled The Loop."""
    lines = [
        f"# The Loop: Macro Summary (Last {int(days)} Days)",
        "",
        "Historical Loop: AI Market Briefing stories from ``data/loop.db``.",
    ]
    if tag:
        lines.extend(["", f"Filtered to tag `{write_brief.humanize_tag(tag)}`."])
    lines.extend(["", render_market_trends(rows).rstrip(), "", "## At a Glance", ""])

    if not rows:
        lines.append("No stories stored for this window.")
        return "\n".join(lines) + "\n"

    stories = [row_as_story(row) for row in rows]
    sections = write_brief.grouped_sections({"stories": stories})
    lines.extend(write_brief.render_at_a_glance(sections))
    for section, items in sections:
        lines.extend(["", write_brief.tag_heading_markdown(section), ""])
        for story, extra_sources in items:
            lines.append(write_brief.render_headline_item(story, extra_sources))
    return "\n".join(lines) + "\n"


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_macro_payload(raw: object) -> dict[str, Any] | None:
    """Return stored briefing JSON with daily_summary and/or tag_notes."""
    data: object = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    summary = data.get("daily_summary")
    notes = data.get("tag_notes")
    daily = summary.strip() if isinstance(summary, str) else ""
    tag_notes = notes if isinstance(notes, dict) else {}
    cleaned_notes = {
        key: value.strip()
        for key, value in tag_notes.items()
        if isinstance(key, str) and isinstance(value, str) and value.strip()
    }
    if not daily and not cleaned_notes:
        return None
    return {"daily_summary": daily, "tag_notes": cleaned_notes}


def load_macro_reports(
    days: int = 14,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load unique daily ``macro_report`` payloads for the last N days.

    Missing database files and empty or invalid ``macro_report`` values return
    an empty list. Never invents briefing copy.
    """
    path = Path(db_path) if db_path is not None else db.DEFAULT_DB_PATH
    if not path.is_file():
        return []
    modifier = f"-{int(days)} days"
    sql = (
        "SELECT published_date, macro_report FROM stories "
        "WHERE published_date >= date('now', ?) "
        "ORDER BY published_date DESC, id DESC"
    )
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(db.SCHEMA)
        cursor = connection.execute(sql, (modifier,))
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()

    payloads: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    seen_bodies: set[str] = set()
    for row in rows:
        parsed = parse_macro_payload(row.get("macro_report"))
        if parsed is None:
            continue
        day = str(row.get("published_date") or "").strip()
        body = json.dumps(parsed, sort_keys=True)
        if day:
            if day in seen_dates:
                continue
            seen_dates.add(day)
        elif body in seen_bodies:
            continue
        seen_bodies.add(body)
        payloads.append(
            {
                "published_date": day,
                "daily_summary": parsed["daily_summary"],
                "tag_notes": parsed["tag_notes"],
            }
        )
    return payloads


def mock_trajectory_report(days: int = 14) -> dict[str, Any]:
    """Deterministic offline trajectory used only with ``--mock``."""
    window = int(days)
    return {
        "narrative_arcs": [
            f"Mock arc 1: policy and markets stay linked across the last {window} days.",
            "Mock arc 2: labor and rates remain a persistent briefing thread.",
            "Mock arc 3: trade and technology stay coupled in stored tag notes.",
            "Mock arc 4: valuations and deal flow follow the same multi-week path.",
        ],
        "signal_momentum": {
            "gaining": [
                "Mock gaining: US Politics",
                "Mock gaining: Tech & Innovation",
            ],
            "fading": ["Mock fading: Venture & M&A"],
        },
        "pivot_points": [
            "Mock pivot: a policy reversal in the stored window.",
            "Mock pivot: a market snapshot shift in Fed Funds or indexes.",
        ],
    }


def empty_trajectory_report() -> dict[str, Any]:
    return {
        "narrative_arcs": [],
        "signal_momentum": {"gaining": [], "fading": []},
        "pivot_points": [],
        "empty": True,
    }


def parse_trajectory_report(text: str) -> dict[str, Any]:
    """Accept JSON trajectory copy from Gemini."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.lstrip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3].rstrip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Trajectory response was not JSON.")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Trajectory response was not a JSON object.")
    momentum = data.get("signal_momentum")
    gaining: list[str] = []
    fading: list[str] = []
    if isinstance(momentum, dict):
        gaining = _string_list(momentum.get("gaining"))
        fading = _string_list(momentum.get("fading"))
    elif isinstance(momentum, list):
        gaining = _string_list(momentum)
    arcs = _string_list(data.get("narrative_arcs"))
    pivots = _string_list(data.get("pivot_points"))
    if not arcs and not gaining and not fading and not pivots:
        raise ValueError("Trajectory response missed narrative, momentum, and pivots.")
    return {
        "narrative_arcs": arcs,
        "signal_momentum": {"gaining": gaining, "fading": fading},
        "pivot_points": pivots,
    }


def format_macro_window(payloads: list[dict[str, Any]], days: int) -> str:
    lines = [
        f"STORED DAILY SUMMARIES AND TAG NOTES FROM THE LAST {int(days)} DAYS:"
    ]
    if not payloads:
        lines.append("(none; do not invent a trajectory)")
        return "\n".join(lines)
    for item in payloads:
        day = item.get("published_date") or "(undated)"
        lines.append(f"[{day}]")
        daily = item.get("daily_summary") or "(none)"
        lines.append(f"daily_summary: {daily}")
        notes = item.get("tag_notes") if isinstance(item.get("tag_notes"), dict) else {}
        if notes:
            for tag, note in notes.items():
                lines.append(f"  {tag}: {note}")
        else:
            lines.append("  tag_notes: (none)")
    return "\n".join(lines)


def render_trajectory_markdown(report: dict[str, Any], days: int) -> str:
    """Render the three trajectory blocks under the Macro Trajectory header."""
    lines = [f"# Macro Trajectory (Last {int(days)} Days)", ""]
    if report.get("empty"):
        lines.append(
            "No stored daily summaries or tag notes for this window; "
            "Loop cannot invent a trajectory."
        )
        return "\n".join(lines) + "\n"
    if report.get("unavailable"):
        lines.append(
            "Trajectory synthesis was unavailable; the rest of The Loop is unchanged."
        )
        return "\n".join(lines) + "\n"

    lines.extend(["## Narrative Arcs", ""])
    arcs = _string_list(report.get("narrative_arcs"))
    if arcs:
        for index, arc in enumerate(arcs, start=1):
            lines.append(f"{index}. {arc}")
    else:
        lines.append("No persistent narrative arcs in this window.")
    lines.append("")

    momentum = report.get("signal_momentum")
    if not isinstance(momentum, dict):
        momentum = {}
    gaining = _string_list(momentum.get("gaining"))
    fading = _string_list(momentum.get("fading"))
    lines.extend(["## Signal Momentum", "", "Gaining:"])
    if gaining:
        for topic in gaining:
            lines.append(f"- {topic}")
    else:
        lines.append("- (none)")
    lines.extend(["", "Fading:"])
    if fading:
        for topic in fading:
            lines.append(f"- {topic}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.extend(["## Pivot Points", ""])
    pivots = _string_list(report.get("pivot_points"))
    if pivots:
        for point in pivots:
            lines.append(f"- {point}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def prepend_trajectory_section(report: str, trajectory_markdown: str) -> str:
    """Insert trajectory markdown directly under the main header; leave the rest."""
    body = report if report.endswith("\n") else report + "\n"
    chunk = trajectory_markdown if trajectory_markdown.endswith("\n") else trajectory_markdown + "\n"
    if not chunk.endswith("\n\n"):
        chunk += "\n"
    lines = body.splitlines(keepends=True)
    if not lines:
        return chunk
    insert_at = 1
    if insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    return "".join(lines[:insert_at]) + chunk + "".join(lines[insert_at:])


def synthesize_trajectory(
    days: int = 14,
    mock: bool = False,
    db_path: Path | None = None,
    payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build trajectory JSON from stored macro reports, mock copy, or Gemini."""
    if mock:
        return mock_trajectory_report(days)
    records = payloads if payloads is not None else load_macro_reports(days, db_path)
    if not records:
        return empty_trajectory_report()
    summarize_stories.load_project_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"unavailable": True, **empty_trajectory_report(), "empty": False}
    prompt = "\n\n".join(
        [
            "Write the macro trajectory from the stored briefing copy below.",
            format_macro_window(records, days),
            "Return JSON only with narrative_arcs, signal_momentum, and pivot_points.",
        ]
    )
    try:
        text, _model = summarize_stories.generate_with_gemini_cascade(
            prompt,
            api_key,
            system_prompt=TRAJECTORY_SYSTEM_PROMPT,
        )
        return parse_trajectory_report(text)
    except (
        summarize_stories.SummarizationError,
        ValueError,
        json.JSONDecodeError,
        KeyError,
    ):
        return {"unavailable": True, **empty_trajectory_report(), "empty": False}


def open_loop_file(output_path: Path) -> None:
    """Open the report with macOS ``open``. No-op on other platforms."""
    if sys.platform != "darwin":
        print(
            f"--open is supported on macOS only; report remains at {output_path}"
        )
        return
    try:
        subprocess.run(["open", str(output_path)], check=False)
    except OSError as error:
        print(f"Could not open {output_path}: {error}")


def save_the_loop(
    output_path: Path | None = None,
    db_path: Path | None = None,
    days: int = 14,
    tag: str | None = None,
    limit: int = 15,
    synthesize: bool = False,
    mock: bool = False,
) -> Path:
    """Write ``briefs/THE_LOOP.md`` from the SQLite history."""
    path = Path(output_path) if output_path is not None else DEFAULT_OUTPUT
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = query_stories(days=days, tag=tag, limit=limit, db_path=db_path)
    report = render_the_loop(rows, days=days, tag=tag)
    if synthesize:
        trajectory = synthesize_trajectory(days=days, mock=mock, db_path=db_path)
        report = prepend_trajectory_section(
            report, render_trajectory_markdown(trajectory, days)
        )
    path.write_text(report, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> Path:
    args = parse_arguments(argv)
    saved = save_the_loop(
        output_path=args.out,
        days=args.days,
        tag=args.tag,
        limit=args.limit,
        synthesize=args.synthesize,
        mock=args.mock,
    )
    print(f"Saved The Loop to {saved}")
    if args.open_after:
        open_loop_file(saved)
    return saved


if __name__ == "__main__":
    main()
