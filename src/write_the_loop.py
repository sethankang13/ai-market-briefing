"""Render a historical Loop report from data/loop.db.

Daily briefs use ``# Looping... (YYYY-MM-DD)``. Aggregated history uses
``# The Loop``.

Run from the project folder:
    python3 src/write_the_loop.py
"""

from __future__ import annotations

import json
from pathlib import Path

import db


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIEFS_DIRECTORY = PROJECT_ROOT / "briefs"


def render_the_loop(rows: list[dict]) -> str:
    """Render stored stories as a historical Markdown report titled The Loop."""
    lines = ["# The Loop", "", "Historical Loop: AI Market Briefing stories.", ""]
    if not rows:
        lines.append("No stories stored yet.")
        return "\n".join(lines) + "\n"

    current_date = None
    for row in rows:
        published = row.get("published_date") or "Unknown date"
        if published != current_date:
            current_date = published
            lines.extend([f"## {published}", ""])
        headline = row.get("headline") or "(untitled)"
        url = row.get("url") or ""
        source = row.get("source") or "Unknown source"
        if url:
            lines.append(f"- [{headline}]({url}) — {source}")
        else:
            lines.append(f"- {headline} — {source}")
        tags = row.get("tags")
        try:
            parsed = json.loads(tags) if isinstance(tags, str) else tags
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list) and parsed:
            hashes = " ".join(f"#{tag}" for tag in parsed)
            lines.append(f"  *Tags: {hashes}*")
        summary = row.get("ai_summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"  Why It Matters: {summary.strip()}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_the_loop(output_path: Path | None = None, db_path: Path | None = None) -> Path:
    """Write ``briefs/the-loop.md`` from the SQLite history."""
    path = output_path or (BRIEFS_DIRECTORY / "the-loop.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_the_loop(db.load_stories(db_path)), encoding="utf-8")
    return path


if __name__ == "__main__":
    saved = save_the_loop()
    print(f"Saved The Loop to {saved}")
