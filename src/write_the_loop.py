"""Render a historical Loop report from data/loop.db.

Daily briefs use ``# Looping... (YYYY-MM-DD)``. Aggregated history uses
``# The Loop: Macro Summary (Last N Days)``.

Run from the project folder:
    python3 src/write_the_loop.py
    python3 src/write_the_loop.py --days 14 --tag Copyright-&-IP --limit 15
    python3 src/write_the_loop.py --open
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import db
import fetch_market
import write_brief
from config_loader import load_config, project_path


_CONFIG = load_config()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = project_path(_CONFIG["pipeline"]["output_dir"]) / "THE_LOOP.md"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a historical Loop macro summary from data/loop.db."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Include stories with published_date in the last N days (default 7).",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Keep rows whose stored tags contain this label, e.g. Legislation-&-Policy.",
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
    return parser.parse_args(argv)


def query_stories(
    days: int = 7,
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
    days: int = 7,
    tag: str | None = None,
) -> str:
    """Render stored stories as a historical Markdown report titled The Loop."""
    lines = [
        f"# The Loop: Macro Summary (Last {int(days)} Days)",
        "",
        "Historical Loop: AI Market Briefing stories from ``data/loop.db``.",
    ]
    if tag:
        lines.extend(["", f"Filtered to tag `{tag}`."])
    lines.extend(["", render_market_trends(rows).rstrip(), "", "## At a Glance", ""])

    if not rows:
        lines.append("No stories stored for this window.")
        return "\n".join(lines) + "\n"

    stories = [row_as_story(row) for row in rows]
    used_slugs: set[str] = set()
    glance: list[tuple[str, str, str]] = []
    detail_blocks: list[str] = []
    for section, items in write_brief.grouped_sections({"stories": stories}):
        assigned = []
        for story, extra_sources in items:
            slug = write_brief.unique_slug(story.get("headline"), used_slugs)
            link = str(story.get("link") or story.get("url") or "").strip()
            glance.append((str(story["headline"]), slug, link))
            assigned.append(write_brief.render_story(story, extra_sources, slug))
        detail_blocks.extend(["", f"## {section}", "", *assigned])

    for headline, slug, link in glance:
        lines.append(write_brief.glance_markdown(headline, link, slug))
    lines.extend(detail_blocks)
    return "\n".join(lines) + "\n"


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
    days: int = 7,
    tag: str | None = None,
    limit: int = 15,
) -> Path:
    """Write ``briefs/THE_LOOP.md`` from the SQLite history."""
    path = Path(output_path) if output_path is not None else DEFAULT_OUTPUT
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = query_stories(days=days, tag=tag, limit=limit, db_path=db_path)
    path.write_text(render_the_loop(rows, days=days, tag=tag), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> Path:
    args = parse_arguments(argv)
    saved = save_the_loop(
        output_path=args.out,
        days=args.days,
        tag=args.tag,
        limit=args.limit,
    )
    print(f"Saved The Loop to {saved}")
    if args.open_after:
        open_loop_file(saved)
    return saved


if __name__ == "__main__":
    main()
