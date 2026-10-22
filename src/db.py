"""SQLite history for Loop: AI Market Briefing.

Each briefing run appends selected stories to ``data/loop.db``. The database
file is gitignored.

Run from the project folder:
    python3 src/db.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from config_loader import load_config, project_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = project_path(load_config()["pipeline"]["db_path"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    published_date TEXT,
    headline TEXT,
    url TEXT,
    source TEXT,
    full_text TEXT,
    ai_summary TEXT,
    tags TEXT,
    market_snapshot_json TEXT
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open loop.db, creating the parent directory and schema if needed."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(SCHEMA)
    connection.commit()
    return connection


def _tags_text(tags: object) -> str:
    if isinstance(tags, str):
        return tags
    if isinstance(tags, list):
        return json.dumps(tags)
    return "[]"


def append_stories(
    stories: Iterable[dict[str, Any]],
    market_snapshot: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> int:
    """Append one run's stories. Returns the number of rows inserted."""
    snapshot_json = json.dumps(market_snapshot) if market_snapshot is not None else None
    rows = []
    for story in stories:
        rows.append(
            (
                story.get("published_at") or story.get("published_date"),
                story.get("headline"),
                story.get("link") or story.get("url"),
                story.get("source"),
                story.get("full_text") or "",
                story.get("ai_summary"),
                _tags_text(story.get("tags")),
                snapshot_json,
            )
        )
    connection = connect(db_path)
    try:
        connection.executemany(
            """
            INSERT INTO stories (
                published_date, headline, url, source, full_text,
                ai_summary, tags, market_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
        return len(rows)
    finally:
        connection.close()


def load_stories(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return stored rows in insertion order."""
    connection = connect(db_path)
    try:
        cursor = connection.execute(
            "SELECT id, published_date, headline, url, source, full_text, "
            "ai_summary, tags, market_snapshot_json FROM stories ORDER BY id"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


if __name__ == "__main__":
    path = DEFAULT_DB_PATH
    print(f"Loop history database: {path}")
    print(f"Stored stories: {len(load_stories(path))}")
