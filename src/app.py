"""Phase 1 local Streamlit UI for Loop: AI Market Briefing.

Reads existing ``briefs/YYYY-MM-DD.md`` files and ``data/loop.db``.
Does not call Gemini, OpenAI, or any other model.

Run from the project folder:
    streamlit run src/app.py
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path(__file__).resolve().parent
BRIEF_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_MD_HTTP_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_GLANCE_SLUG_LINK = re.compile(r"^(\s*-\s*)\[([^\]]+)\]\(#([^)]+)\)\s*$", re.M)
_BARE_URL_LINE = re.compile(r"^[ \t]*(?:[-*]\s*)?(https?://\S+)\s*$", re.M)
_ANCHOR_STORY = re.compile(
    r'<a id="([^"]+)"></a>\s*\n-\s*\[([^\]]+)\]\((https?://[^)]+)\)'
)

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


def normalize_headline(headline: object) -> str:
    """Collapse whitespace and lowercase so exact headlines group together."""
    return " ".join(str(headline or "").lower().split())


def headline_markdown(headline: object, url: object = None) -> str:
    """Render a heading as a Markdown link, never a bare URL."""
    text = str(headline or "").strip() or "(untitled)"
    href = str(url or "").strip()
    if href:
        return f"### [{text}]({href})"
    return f"### **{text}**"


def headline_html(headline: object, url: object = None) -> str:
    """Same heading with ``target=_blank`` when Streamlit allows HTML."""
    text = html.escape(str(headline or "").strip() or "(untitled)")
    href = str(url or "").strip()
    if href:
        safe = html.escape(href, quote=True)
        return (
            f'### <a href="{safe}" target="_blank" rel="noopener noreferrer">{text}</a>'
        )
    return f"### **{text}**"


def source_bullet_markdown(source: object, title: object, url: object = None) -> str:
    label = f"{source or 'Unknown source'}: {title or '(untitled)'}"
    href = str(url or "").strip()
    if href:
        return f"- [{label}]({href})"
    return f"- **{label}**"


def display_brief_markdown(markdown: str) -> str:
    """Hyperlink At a Glance / titles to RSS URLs; drop standalone URL lines."""
    slug_to_url: dict[str, str] = {}
    for match in _ANCHOR_STORY.finditer(markdown):
        slug_to_url[match.group(1)] = match.group(3)
    headline_to_url: dict[str, str] = {}
    for title, url in _MD_HTTP_LINK.findall(markdown):
        headline_to_url[title] = url
        headline_to_url[normalize_headline(title)] = url

    def replace_glance(match: re.Match[str]) -> str:
        prefix, title, slug = match.group(1), match.group(2), match.group(3)
        url = (
            slug_to_url.get(slug)
            or headline_to_url.get(title)
            or headline_to_url.get(normalize_headline(title))
        )
        if url:
            return f"{prefix}[{title}]({url})"
        return match.group(0)

    rewritten = _GLANCE_SLUG_LINK.sub(replace_glance, markdown)
    rewritten = _BARE_URL_LINE.sub("", rewritten)
    return rewritten


def source_popover_items(rows: list[dict]) -> list[dict]:
    """Unique publisher/title/url rows for an explorer popover."""
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        source = str(row.get("source") or "Unknown source").strip() or "Unknown source"
        title = str(row.get("headline") or "(untitled)").strip() or "(untitled)"
        url = str(row.get("url") or "").strip()
        key = (source, title, url)
        if key in seen:
            continue
        seen.add(key)
        items.append({"source": source, "headline": title, "url": url})
    return items


def group_stories_by_headline(rows: list[dict]) -> list[dict]:
    """Collapse exact RSS headlines (one URL per SQLite row) like write_brief."""
    groups: list[dict] = []
    index: dict[str, int] = {}
    for row_number, row in enumerate(rows):
        key = normalize_headline(row.get("headline"))
        if not key:
            key = f"__row_{row_number}"
        if key in index:
            groups[index[key]]["coverage"].append(row)
            continue
        index[key] = len(groups)
        groups.append(
            {
                "headline": row.get("headline") or "(untitled)",
                "url": str(row.get("url") or "").strip(),
                "published_date": row.get("published_date") or "",
                "source": row.get("source") or "Unknown source",
                "tags": row.get("tags") or [],
                "ai_summary": row.get("ai_summary") or "",
                "coverage": [row],
            }
        )
    for group in groups:
        group["sources"] = source_popover_items(group["coverage"])
        if not group["url"]:
            for item in group["sources"]:
                if item["url"]:
                    group["url"] = item["url"]
                    break
    return groups


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
        "SELECT published_date, headline, url, source, tags, ai_summary "
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
                "url": row["url"] or "",
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
    st.markdown(display_brief_markdown(markdown), unsafe_allow_html=True)


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
    groups = group_stories_by_headline(rows)
    st.caption(f"{len(groups)} matching stor{'y' if len(groups) == 1 else 'ies'}")
    if not groups:
        st.info("No stored articles match those filters.")
        return
    for index, group in enumerate(groups):
        title = group["headline"]
        with st.expander(title, expanded=index == 0):
            st.markdown(headline_html(group["headline"], group["url"]), unsafe_allow_html=True)
            st.write(f"**Source:** {group['source']}")
            st.write(f"**Date:** {group['published_date']}")
            tags_text = ", ".join(group["tags"]) if group["tags"] else "(none)"
            st.write(f"**Tags:** {tags_text}")
            st.write(group["ai_summary"] or "(no summary)")
            coverage = group["sources"]
            if len(coverage) > 1:
                with st.popover(f"🔗 Sources ({len(coverage)})"):
                    for item in coverage:
                        st.markdown(
                            source_bullet_markdown(
                                item["source"], item["headline"], item["url"]
                            )
                        )


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
