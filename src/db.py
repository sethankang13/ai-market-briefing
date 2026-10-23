"""SQLite history for Loop: AI Market Briefing.

Each briefing run appends selected stories to ``data/loop.db``. The database
file is gitignored. Existing rows are never deleted; new columns are added
with ``ALTER TABLE``.

Run from the project folder:
    python3 src/db.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime
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
    market_snapshot_json TEXT,
    macro_report TEXT
);
"""

RECENT_STORIES_SQL = (
    "SELECT id, published_date, headline, url, source, full_text, "
    "ai_summary, tags, market_snapshot_json, macro_report FROM stories "
    "WHERE published_date >= date('now', '-14 days') "
    "ORDER BY published_date DESC, id DESC"
)


def iso_published_date(value: object) -> str | None:
    """Store YYYY-MM-DD when the RSS date can be parsed; otherwise the original text."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            return parsed.date().isoformat()
        return parsed.date().isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        iso = text[:-1] + "+00:00" if text.endswith("Z") else text
        return datetime.fromisoformat(iso).date().isoformat()
    except ValueError:
        return text


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open loop.db, creating the parent directory and schema if needed."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the table or add missing columns. Never drops existing rows."""
    connection.execute(SCHEMA)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(stories)").fetchall()
    }
    if "macro_report" not in columns:
        connection.execute("ALTER TABLE stories ADD COLUMN macro_report TEXT")
    connection.commit()


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
    macro_report: str | None = None,
) -> int:
    """Append one run's stories. Returns the number of rows inserted."""
    snapshot_json = json.dumps(market_snapshot) if market_snapshot is not None else None
    rows = []
    for story in stories:
        snippet = story.get("full_text") or story.get("description") or ""
        rows.append(
            (
                iso_published_date(
                    story.get("published_at") or story.get("published_date")
                ),
                story.get("headline"),
                story.get("link") or story.get("url"),
                story.get("source"),
                snippet,
                story.get("ai_summary"),
                _tags_text(story.get("tags")),
                snapshot_json,
                macro_report if macro_report is not None else story.get("macro_report"),
            )
        )
    connection = connect(db_path)
    try:
        connection.executemany(
            """
            INSERT INTO stories (
                published_date, headline, url, source, full_text,
                ai_summary, tags, market_snapshot_json, macro_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            "ai_summary, tags, market_snapshot_json, macro_report "
            "FROM stories ORDER BY id"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def load_recent_stories(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Load stored briefing records from the last 14 days. Does not invent rows.

    Uses parameterized SQLite:
    ``WHERE published_date >= date('now', '-14 days')``.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    if not path.is_file():
        return []
    connection = connect(path)
    try:
        cursor = connection.execute(RECENT_STORIES_SQL)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


if __name__ == "__main__":
    path = DEFAULT_DB_PATH
    print(f"Loop history database: {path}")
    print(f"Stored stories: {len(load_stories(path))}")
