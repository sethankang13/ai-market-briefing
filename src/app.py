"""Phase 1 local Streamlit UI for Loop: AI Market Briefing.

Reads existing ``briefs/YYYY-MM-DD.md`` files and ``data/loop.db``.
Does not call Gemini, OpenAI, or any other model.

Run from the project folder:
    streamlit run src/app.py
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path(__file__).resolve().parent
BRIEF_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
from config_loader import load_config, project_path


def ensure_project_root() -> Path:
    """Make ``config/``, ``briefs/``, and ``data/`` resolvable from this file."""
    os.chdir(PROJECT_ROOT)
    return PROJECT_ROOT


def briefs_directory() -> Path:
    return project_path(load_config()["pipeline"]["output_dir"])


def db_path() -> Path:
    return project_path(load_config()["pipeline"]["db_path"])


def list_briefing_dates(briefs_dir: Path | None = None) -> list[str]:
    """Return YYYY-MM-DD dates for briefing files, newest first."""
    directory = briefs_dir if briefs_dir is not None else briefs_directory()
    if not directory.is_dir():
        return []
    dates = []
    for path in directory.iterdir():
        match = BRIEF_NAME.fullmatch(path.name)
        if match and path.is_file():
            dates.append(match.group(1))
    dates.sort(reverse=True)
    return dates


def latest_briefing_date(briefs_dir: Path | None = None) -> str | None:
    dates = list_briefing_dates(briefs_dir)
    return dates[0] if dates else None


def load_briefing_markdown(date: str, briefs_dir: Path | None = None) -> str | None:
    directory = briefs_dir if briefs_dir is not None else briefs_directory()
    path = directory / f"{date}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def taxonomy_tags(config: dict | None = None) -> list[str]:
    settings = config if config is not None else load_config()
    taxonomy = settings.get("taxonomy") or {}
    return list(taxonomy.keys())


def active_feed_count(config: dict | None = None) -> int:
    settings = config if config is not None else load_config()
    feeds = settings.get("feeds") or {}
    return len(feeds)


def parse_tags(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [tag for tag in raw if isinstance(tag, str) and tag]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(parsed, list):
        return [tag for tag in parsed if isinstance(tag, str) and tag]
    return [raw]


@st.cache_resource
def get_connection(db_path_str: str) -> sqlite3.Connection:
    """Reuse one SQLite connection (not pickleable; not ``st.cache_data``)."""
    connection = sqlite3.connect(db_path_str, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@st.cache_data
def count_stored_articles(db_path_str: str) -> int:
    path = Path(db_path_str)
    if not path.is_file():
        return 0
    connection = get_connection(db_path_str)
    try:
        row = connection.execute("SELECT COUNT(*) AS n FROM stories").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"] if row is not None else 0)


@st.cache_data
def unique_sources(db_path_str: str) -> list[str]:
    path = Path(db_path_str)
    if not path.is_file():
        return []
    connection = get_connection(db_path_str)
    try:
        cursor = connection.execute(
            "SELECT DISTINCT source FROM stories "
            "WHERE source IS NOT NULL AND source != '' "
            "ORDER BY source"
        )
    except sqlite3.Error:
        return []
    return [row["source"] for row in cursor.fetchall()]


@st.cache_data
def search_stories(
    db_path_str: str,
    tag: str,
    source: str,
    query: str,
) -> list[dict]:
    """Filter stored stories with bound parameters only (no SQL interpolation)."""
    path = Path(db_path_str)
    if not path.is_file():
        return []
    connection = get_connection(db_path_str)
    sql = (
        "SELECT published_date, headline, source, tags, ai_summary "
        "FROM stories WHERE 1=1"
    )
    params: list[object] = []
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if source:
        sql += " AND source = ?"
        params.append(source)
    if query:
        sql += " AND (headline LIKE ? OR ai_summary LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY published_date DESC, id DESC"
    try:
        cursor = connection.execute(sql, params)
    except sqlite3.Error:
        return []
    rows = []
    for row in cursor.fetchall():
        rows.append(
            {
                "published_date": row["published_date"] or "",
                "headline": row["headline"] or "(untitled)",
                "source": row["source"] or "Unknown source",
                "tags": parse_tags(row["tags"]),
                "ai_summary": row["ai_summary"] or "",
            }
        )
    return rows


def render_sidebar(path: Path, latest: str | None, feed_count: int) -> None:
    with st.sidebar:
        st.header("Loop: AI Market Briefing")
        st.metric("Stored articles", count_stored_articles(str(path)))
        st.metric("Latest brief", latest or "None")
        st.metric("Active feeds", feed_count)


def render_daily_briefings() -> None:
    dates = list_briefing_dates()
    if not dates:
        st.info("No daily briefings found in briefs/. Generate one with the pipeline first.")
        return
    selected = st.selectbox("Briefing date", dates, index=0)
    markdown = load_briefing_markdown(selected)
    if markdown is None:
        st.warning(f"Could not read briefs/{selected}.md.")
        return
    st.markdown(markdown, unsafe_allow_html=True)


def render_loop_explorer(path: Path) -> None:
    if not path.is_file():
        st.info("No Loop history database yet. data/loop.db is created when a briefing run appends stories.")
        return
    tags = ["All tags"] + taxonomy_tags()
    sources = ["All sources"] + unique_sources(str(path))
    tag_choice = st.selectbox("Taxonomy tag", tags)
    source_choice = st.selectbox("Source", sources)
    query = st.text_input("Search headline or summary")
    tag = "" if tag_choice == "All tags" else tag_choice
    source = "" if source_choice == "All sources" else source_choice
    rows = search_stories(str(path), tag, source, query.strip())
    st.caption(f"{len(rows)} matching stor{'y' if len(rows) == 1 else 'ies'}")
    if not rows:
        st.info("No stored articles match those filters.")
        return
    for index, row in enumerate(rows):
        title = row["headline"]
        with st.expander(title, expanded=index == 0):
            st.write(f"**Source:** {row['source']}")
            st.write(f"**Date:** {row['published_date']}")
            tags_text = ", ".join(row["tags"]) if row["tags"] else "(none)"
            st.write(f"**Tags:** {tags_text}")
            st.write(row["ai_summary"] or "(no summary)")


def main() -> None:
    ensure_project_root()
    st.set_page_config(
        page_title="Loop: AI Market Briefing",
        page_icon="🔁",
        layout="wide",
    )
    path = db_path()
    render_sidebar(path, latest_briefing_date(), active_feed_count())
    daily_tab, explorer_tab = st.tabs(["Daily Briefings", "The Loop Explorer"])
    with daily_tab:
        render_daily_briefings()
    with explorer_tab:
        render_loop_explorer(path)


if __name__ == "__main__":
    main()
