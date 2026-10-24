"""Local Streamlit UI for Loop: AI Market Briefing.

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
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
LOCK_PATH = PROJECT_ROOT / "logs" / "briefing.lock"
BRIEF_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_MD_HTTP_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_GLANCE_SLUG_LINK = re.compile(r"^(\s*-\s*)\[([^\]]+)\]\(#([^)]+)\)\s*$", re.M)
_BARE_URL_LINE = re.compile(r"^[ \t]*(?:[-*]\s*)?(https?://\S+)\s*$", re.M)
_ANCHOR_STORY = re.compile(
    r'<a id="([^"]+)"></a>\s*\n-\s*\[([^\]]+)\]\((https?://[^)]+)\)'
)
_LOOPING_TITLE = re.compile(r"^# Looping\.\.\. \(([^)]+)\)\s*$", re.M)
TAB_DAILY = "Daily Loop"
TAB_LOOP = "The Loop"
SCROLL_CSS = """
<style>
a[id], h1, h2, h3, [id] { scroll-margin-top: 90px; }
</style>
"""

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
from config_loader import load_config, project_path
from write_brief import (
    TAG_ARCHIVE_BASE,
    TAG_LABELS,
    humanize_tag,
    tag_archive_url,
    tag_hashtag_html,
)


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
        if match and path.is_file() and path.stat().st_size > 0:
            dates.append(match.group(1))
    dates.sort(reverse=True)
    return dates


def latest_briefing_date(briefs_dir: Path | None = None) -> str | None:
    dates = list_briefing_dates(briefs_dir)
    return dates[0] if dates else None


def load_briefing_markdown(date: str, briefs_dir: Path | None = None) -> str | None:
    directory = briefs_dir if briefs_dir is not None else briefs_directory()
    path = directory / f"{date}.md"
    if not path.is_file() or path.stat().st_size == 0:
        return None
    return path.read_text(encoding="utf-8")


def taxonomy_tags(config: dict | None = None) -> list[str]:
    settings = config if config is not None else load_config()
    taxonomy = settings.get("taxonomy") or {}
    return list(taxonomy.keys())


def active_feed_names(config: dict | None = None) -> list[str]:
    settings = config if config is not None else load_config()
    feeds = settings.get("feeds") or {}
    return list(feeds.keys())


def active_feed_count(config: dict | None = None) -> int:
    return len(active_feed_names(config))


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


def humanize_brief_markdown(markdown: str) -> str:
    """User-facing labels and Daily Loop title; internal keys in URLs stay."""
    rewritten = _LOOPING_TITLE.sub("", markdown, count=1)
    rewritten = re.sub(
        r"^## Daily Summary(?: & Research Topics)?\s*$",
        "## Daily Summary & Research Topics",
        rewritten,
        flags=re.M,
    )
    for tag in list(TAG_LABELS) + ["Other"]:
        human = humanize_tag(tag)
        rewritten = rewritten.replace(f"## {tag}", f"## {human}")
        escaped = html.escape(tag)
        human_escaped = html.escape(human)
        if escaped != human_escaped:
            rewritten = rewritten.replace(f">{escaped}</a>", f">{human_escaped}</a>")
            rewritten = rewritten.replace(f"#{escaped}", human_escaped)
    return rewritten


def display_brief_markdown(markdown: str) -> str:
    """Hyperlink At a Glance / titles to RSS URLs; drop standalone URL lines."""
    markdown = humanize_brief_markdown(markdown)
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


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_briefing_generating(lock_path: Path | None = None) -> bool:
    """True when run_daily.sh holds a live lock (or a live run_briefing pid)."""
    path = lock_path if lock_path is not None else LOCK_PATH
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw.isdigit() and pid_is_running(int(raw)):
            return True
        if raw.isdigit() and not pid_is_running(int(raw)):
            return False
        return True
    return False


def today_iso() -> str:
    return date.today().isoformat()


def generating_banner(today: str) -> str:
    return (
        f"⏳ Today's briefing ({today}) is currently generating in the background. "
        "Showing latest available brief."
    )


def ready_banner(today: str) -> str:
    return f"🎉 A new briefing for {today} is now ready!"


def arm_generation_poll(generating: bool) -> None:
    """Reload when a background briefing finishes, without blocking this run."""
    if not generating:
        return
    fragment = getattr(st, "fragment", None)
    if not callable(fragment):
        return

    def _tick() -> None:
        if not is_briefing_generating():
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()

    try:
        fragment(run_every=timedelta(seconds=5))(_tick)()
    except TypeError:
        return


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
def unique_published_dates(db_path_str: str) -> list[str]:
    path = Path(db_path_str)
    if not path.is_file():
        return []
    connection = get_connection(db_path_str)
    try:
        cursor = connection.execute(
            "SELECT DISTINCT published_date FROM stories "
            "WHERE published_date IS NOT NULL AND published_date != '' "
            "ORDER BY published_date DESC"
        )
    except sqlite3.Error:
        return []
    return [row["published_date"] for row in cursor.fetchall()]


@st.cache_data
def read_query_tag(query_params=None) -> str | None:
    """Read ``?tag=`` from Streamlit query params, or from an injected mapping."""
    params = query_params
    if params is None:
        params = getattr(st, "query_params", None)
        if params is None:
            getter = getattr(st, "experimental_get_query_params", None)
            params = getter() if callable(getter) else {}
    if params is None:
        return None
    value = None
    if hasattr(params, "get"):
        value = params.get("tag")
    elif isinstance(params, dict):
        value = params.get("tag")
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def stories_for_tag(db_path_str: str, tag: str) -> list[dict]:
    """All loop.db rows whose tags contain ``tag``. Uses bound ``tags LIKE ?``."""
    return search_stories(db_path_str, tag, "", "")


def group_stories_by_date(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Newest date first; preserve row order within each date."""
    grouped: list[tuple[str, list[dict]]] = []
    index: dict[str, int] = {}
    for row in rows:
        date_value = str(row.get("published_date") or "").strip() or "(unknown date)"
        if date_value in index:
            grouped[index[date_value]][1].append(row)
            continue
        index[date_value] = len(grouped)
        grouped.append((date_value, [row]))
    return grouped


def tag_chips_html(tags: list[str]) -> str:
    """Same colored local chips used in the daily brief (humanized labels)."""
    chips = [tag_hashtag_html(tag) for tag in tags if tag]
    return " ".join(chips)


def search_stories(
    db_path_str: str,
    tag: str,
    source: str,
    query: str,
    year: str = "",
    month: str = "",
    day: str = "",
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
    year = str(year or "").strip()
    month = str(month or "").strip().zfill(2) if str(month or "").strip() else ""
    day = str(day or "").strip().zfill(2) if str(day or "").strip() else ""
    if year and month and day:
        sql += " AND published_date = ?"
        params.append(f"{year}-{month}-{day}")
    elif year and month:
        sql += " AND published_date LIKE ?"
        params.append(f"{year}-{month}-%")
    elif year:
        sql += " AND published_date LIKE ?"
        params.append(f"{year}-%")
    else:
        if month:
            sql += " AND substr(published_date, 6, 2) = ?"
            params.append(month)
        if day:
            sql += " AND substr(published_date, 9, 2) = ?"
            params.append(day)
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


def in_focus_title(tag: str, source: str, query: str, year: str, month: str, day: str) -> str:
    parts: list[str] = []
    if tag:
        parts.append(humanize_tag(tag))
    if source:
        parts.append(source)
    date_parts = [part for part in (year, month, day) if part]
    if date_parts:
        parts.append("-".join(date_parts))
    if query:
        parts.append(f"“{query}”")
    return "In Focus: " + (" · ".join(parts) if parts else "All stories")


def static_asset_is_utf8(path: Path) -> bool:
    """Streamlit reads SVG as UTF-8; latin-1 bytes such as 0xb7 crash st.image."""
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def show_static_image(path: Path, **kwargs) -> bool:
    """Show a local image; skip it if the file is missing or not UTF-8 SVG."""
    if not path.is_file():
        return False
    if path.suffix.lower() == ".svg" and not static_asset_is_utf8(path):
        return False
    try:
        st.image(str(path), **kwargs)
    except (UnicodeDecodeError, OSError, ValueError, TypeError):
        return False
    return True


def page_icon_value() -> str:
    logo = STATIC_DIR / "loop-logo.svg"
    if logo.is_file() and static_asset_is_utf8(logo):
        return str(logo)
    return "🔁"


def render_brand_header() -> None:
    logo = STATIC_DIR / "loop-logo.svg"
    banner = STATIC_DIR / "loop-banner.svg"
    left, right = st.columns([1, 6])
    with left:
        show_static_image(logo, width=88)
    with right:
        show_static_image(banner, use_container_width=True)


def render_sidebar(path: Path, latest: str | None, feed_names: list[str], brief_count: int) -> None:
    with st.sidebar:
        st.header("Loop: AI Market Briefing")
        st.metric("Stored briefings", brief_count)
        st.metric("Latest briefing", latest or "None")
        st.subheader("Active feeds")
        if feed_names:
            for name in feed_names:
                st.caption(name)
        else:
            st.caption("None configured")
        del path


def render_story_cards(groups: list[dict]) -> None:
    st.caption(f"{len(groups)} matching stor{'y' if len(groups) == 1 else 'ies'}")
    if not groups:
        st.info("No stored articles match those filters.")
        return
    for group in groups:
        with st.container(border=True):
            st.markdown(headline_html(group["headline"], group["url"]), unsafe_allow_html=True)
            st.write(f"**Source:** {group['source']}")
            st.write(f"**Date:** {group['published_date']}")
            chips = tag_chips_html(group["tags"])
            if chips:
                st.markdown(chips, unsafe_allow_html=True)
            if group["ai_summary"]:
                st.write(group["ai_summary"])
            coverage = group["sources"]
            if len(coverage) > 1:
                with st.popover(f"🔗 Sources ({len(coverage)})"):
                    for item in coverage:
                        st.markdown(
                            source_bullet_markdown(
                                item["source"], item["headline"], item["url"]
                            )
                        )


def render_daily_loop() -> None:
    today = today_iso()
    generating = is_briefing_generating()
    dates = list_briefing_dates()
    today_exists = today in dates
    if generating:
        st.session_state["was_generating"] = True
        st.info(generating_banner(today))
    elif st.session_state.get("was_generating") and today_exists:
        st.session_state["was_generating"] = False
        st.success(ready_banner(today))
    elif st.session_state.get("briefing_just_ready") == today:
        st.session_state.pop("briefing_just_ready", None)
        st.success(ready_banner(today))

    if not dates:
        st.info("No daily briefings found in briefs/. Generate one with the pipeline first.")
        arm_generation_poll(generating)
        return

    selected = today if today_exists and not generating else dates[0]
    if generating or not today_exists:
        selected = dates[0]
        if selected == today and generating:
            older = [item for item in dates if item != today]
            if older:
                selected = older[0]

    render_brand_header()
    st.title(f"Daily Loop: {selected}")
    markdown = load_briefing_markdown(selected)
    if markdown is None:
        st.warning(f"Could not read briefs/{selected}.md.")
        arm_generation_poll(generating)
        return
    st.markdown(display_brief_markdown(markdown), unsafe_allow_html=True)
    arm_generation_poll(generating)


def _enter_loop_focus() -> None:
    st.session_state["loop_focus"] = True


def render_loop_explorer(path: Path) -> None:
    if not path.is_file():
        st.info(
            "No Loop history database yet. data/loop.db is created when a briefing run appends stories."
        )
        return

    internal_tags = taxonomy_tags()
    tag_options = [""] + internal_tags
    sources = [""] + unique_sources(str(path))
    published = unique_published_dates(str(path))
    years = sorted({item[:4] for item in published if len(item) >= 4}, reverse=True)
    months = [f"{index:02d}" for index in range(1, 13)]
    days = [f"{index:02d}" for index in range(1, 32)]

    def tag_label(value: str) -> str:
        return "All tags" if value == "" else humanize_tag(value)

    def source_label(value: str) -> str:
        return "All sources" if value == "" else value

    def blank_label(value: str, empty: str) -> str:
        return empty if value == "" else value

    if st.session_state.get("loop_focus"):
        if st.button("← Back to Search"):
            st.session_state["loop_focus"] = False
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
            return
        tag = st.session_state.get("loop_tag") or ""
        source = st.session_state.get("loop_source") or ""
        year = st.session_state.get("loop_year") or ""
        month = st.session_state.get("loop_month") or ""
        day = st.session_state.get("loop_day") or ""
        query = (st.session_state.get("loop_query") or "").strip()
        st.header(in_focus_title(tag, source, query, year, month, day))
        rows = search_stories(str(path), tag, source, query, year, month, day)
        render_story_cards(group_stories_by_headline(rows))
        return

    st.selectbox(
        "Tag",
        tag_options,
        format_func=tag_label,
        key="loop_tag",
        on_change=_enter_loop_focus,
    )
    st.selectbox(
        "Source",
        sources,
        format_func=source_label,
        key="loop_source",
        on_change=_enter_loop_focus,
    )
    year_options = [""] + years
    month_options = [""] + months
    day_options = [""] + days
    c1, c2, c3 = st.columns(3)
    with c1:
        st.selectbox(
            "Year",
            year_options,
            format_func=lambda value: blank_label(value, "Any year"),
            key="loop_year",
            on_change=_enter_loop_focus,
        )
    with c2:
        st.selectbox(
            "Month",
            month_options,
            format_func=lambda value: blank_label(value, "Any month"),
            key="loop_month",
            on_change=_enter_loop_focus,
        )
    with c3:
        st.selectbox(
            "Day",
            day_options,
            format_func=lambda value: blank_label(value, "Any day"),
            key="loop_day",
            on_change=_enter_loop_focus,
        )
    st.text_input("Keyword", key="loop_query")
    if st.button("Search"):
        _enter_loop_focus()
        rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
        if callable(rerun):
            rerun()


def render_tag_archive(path: Path, tag: str) -> None:
    """Archive of every stored story with this tag, grouped by date (newest first)."""
    st.markdown(f"## {tag_hashtag_html(tag)}", unsafe_allow_html=True)
    st.caption("Local Loop archive from data/loop.db. Not a public website.")
    st.markdown(f"[Back to Daily Loop]({TAG_ARCHIVE_BASE})")
    if not path.is_file():
        st.info(
            "No Loop history database yet. data/loop.db is created when a briefing run appends stories."
        )
        return
    rows = stories_for_tag(str(path), tag)
    if not rows:
        st.info(f"No stored articles tagged {humanize_tag(tag)}.")
        return
    for date_value, date_rows in group_stories_by_date(rows):
        st.subheader(date_value)
        groups = group_stories_by_headline(date_rows)
        for group in groups:
            st.markdown(headline_html(group["headline"], group["url"]), unsafe_allow_html=True)
            extras = [
                item["source"]
                for item in group["sources"]
                if item["source"] and item["source"] != group["source"]
            ]
            if extras:
                st.caption(f"also covered by [{', '.join(extras)}]")
            chips = tag_chips_html(group["tags"])
            if chips:
                st.markdown(chips, unsafe_allow_html=True)


def main() -> None:
    ensure_project_root()
    st.set_page_config(
        page_title="Loop: AI Market Briefing",
        page_icon=page_icon_value(),
        layout="wide",
    )
    st.markdown(SCROLL_CSS, unsafe_allow_html=True)
    render_brand_header()
    path = db_path()
    dates = list_briefing_dates()
    render_sidebar(path, dates[0] if dates else None, active_feed_names(), len(dates))
    requested = read_query_tag()
    if requested:
        render_tag_archive(path, requested)
        return
    daily_tab, explorer_tab = st.tabs([TAB_DAILY, TAB_LOOP])
    with daily_tab:
        render_daily_loop()
    with explorer_tab:
        render_loop_explorer(path)


if __name__ == "__main__":
    main()
