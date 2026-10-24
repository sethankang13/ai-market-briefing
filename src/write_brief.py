"""Render a readable local Loop briefing from a summarized or selected story run.

Daily files use ``# Looping... (YYYY-MM-DD)``. Historical reports are rendered
separately by ``write_the_loop.py`` as ``# The Loop``.

Run from the project folder:
    python3 src/write_brief.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import urlencode

import fetch_market
from config_loader import load_config, project_path
from tag_stories import TAG_LABELS, primary_tag


_CONFIG = load_config()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARIZED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "summarized"
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
BRIEFS_DIRECTORY = project_path(_CONFIG["pipeline"]["output_dir"])
SECTION_ORDER = TAG_LABELS + ("Other",)
TAG_ARCHIVE_BASE = "http://127.0.0.1:8501/"
# Distinct colors with contrast on a light Streamlit/Markdown background.
TAG_COLORS = {
    "Market-Valuations": "#0B5CAB",
    "Venture-&-M&A": "#1B7F5A",
    "Legislation-&-Policy": "#6B2FA0",
    "Antitrust-&-Compliance": "#B45309",
    "Copyright-&-IP": "#9D174D",
    "Geopolitics-&-Trade": "#B42318",
    "Labor-&-Economy": "#0F6C75",
    "Enterprise-Adoption": "#1D4ED8",
    "Foundation-Models": "#C2410C",
}
PENDING_MARKERS = (
    "AI Summary Pending",
    "AI Headline Pending",
    "AI headline pending",
    "AI Summary goes HERE",
)


def latest_summarized_run(summarized_data_directory=None):
    """Return the newest summarized run, or None when none exist."""
    directory = summarized_data_directory or SUMMARIZED_DATA_DIRECTORY
    summarized_runs = sorted(directory.glob("*.json"))
    return summarized_runs[-1] if summarized_runs else None


def latest_selected_run(selected_data_directory=None):
    """Return the newest selected run, or explain why one cannot be found."""
    directory = selected_data_directory or SELECTED_DATA_DIRECTORY
    selected_runs = sorted(directory.glob("*.json"))
    if not selected_runs:
        raise FileNotFoundError(
            f"No selected story runs found in {directory}. "
            "Run select_stories.py first."
        )
    return selected_runs[-1]


def latest_briefing_source(summarized_data_directory=None, selected_data_directory=None):
    """Prefer a summarized run; fall back to the latest selected run."""
    return latest_summarized_run(summarized_data_directory) or latest_selected_run(
        selected_data_directory
    )


def load_selected_run(input_path: Path) -> dict[str, object]:
    """Load one story run and make sure it has a story list."""
    selected_run = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(selected_run, dict) or not isinstance(selected_run.get("stories"), list):
        raise ValueError(f"{input_path} does not contain a 'stories' list.")
    return selected_run


def story_tags(story: dict[str, object]) -> list[str]:
    """Return assigned tags in taxonomy order, ignoring a missing or non-list value."""
    tags = story.get("tags")
    if not isinstance(tags, list):
        return []
    assigned = {tag for tag in tags if isinstance(tag, str) and tag}
    ordered = [tag for tag in TAG_LABELS if tag in assigned]
    extras = [tag for tag in tags if isinstance(tag, str) and tag and tag not in TAG_LABELS]
    return ordered + extras


def section_for_story(story: dict[str, object]) -> str:
    """Choose one section: the highest-weight assigned tag from config."""
    chosen = primary_tag(story_tags(story))
    return chosen if chosen else "Other"


def humanize_tag(tag: str) -> str:
    """User-facing label: ``-&-`` becomes `` & ``, remaining hyphens become spaces."""
    if not isinstance(tag, str) or not tag:
        return ""
    return tag.replace("-&-", " & ").replace("-", " ")


def tag_archive_url(tag: str, base: str = TAG_ARCHIVE_BASE) -> str:
    """Local Streamlit archive URL for one taxonomy tag (query-parameterized)."""
    root = base if base.endswith("/") else f"{base}/"
    return f"{root}?{urlencode({'tag': tag})}"


def tag_hashtag_html(tag: str, base: str = TAG_ARCHIVE_BASE) -> str:
    """Color-coded chip with a humanized label; href still uses the internal key."""
    color = TAG_COLORS.get(tag, "#334155")
    href = html.escape(tag_archive_url(tag, base), quote=True)
    label = html.escape(humanize_tag(tag))
    return (
        f'<a href="{href}" style="color:{color};font-weight:700;text-decoration:none">'
        f"{label}</a>"
    )


def tag_section_id(tag: str) -> str:
    """Stable HTML id for a plain ``## Tag`` heading (At a Glance jump target)."""
    return slugify(tag)


def tag_heading_markdown(tag: str, base: str = TAG_ARCHIVE_BASE) -> str:
    """Plain Markdown heading plus an anchor. Not a Streamlit link and not colored."""
    del base
    return f'<a id="{tag_section_id(tag)}"></a>\n## {humanize_tag(tag)}'


def tag_chips_html(tags: list[str], base: str = TAG_ARCHIVE_BASE) -> str:
    """Color-coded Streamlit archive chips, in taxonomy order."""
    return " ".join(tag_hashtag_html(tag, base) for tag in tags if tag)


def tags_line(story: dict[str, object]) -> str:
    """Unused in the daily brief; kept so older callers do not import-break."""
    hashes = " ".join(f"#{tag}" for tag in story_tags(story))
    if hashes:
        return f"  *Tags: {hashes}*  "
    return "  *Tags:*  "


def why_it_matters(story: dict[str, object]) -> str | None:
    """Per-story Why It Matters is not written into briefs."""
    return None


def normalize_headline(headline: object) -> str:
    """Collapse whitespace and lowercase so exact headlines group together."""
    return " ".join(str(headline or "").lower().split())


def slugify(headline: object) -> str:
    """Turn an RSS headline into a stable Markdown fragment id."""
    lowered = str(headline or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "story"


def glance_phrase(headline: object) -> str:
    """First three words of the RSS headline, then an ellipsis."""
    words = str(headline or "").split()
    if not words:
        return "(untitled)…"
    return " ".join(words[:3]) + "…"


def glance_markdown(headline: object, url: object, slug: str) -> str:
    """At a Glance phrase: three-word RSS link, or a section-slug fallback."""
    phrase = glance_phrase(headline)
    href = str(url or "").strip()
    if href:
        return f"[{phrase}]({href})"
    return f"[{phrase}](#{slug})"


def glance_tag_label(tag: str) -> str:
    """White italic section jump. Not a hashtag and not a default Markdown link."""
    href = html.escape(f"#{tag_section_id(tag)}", quote=True)
    label = html.escape(humanize_tag(tag))
    return (
        f'<a href="{href}" style="color:#fff;font-style:italic;text-decoration:none">'
        f"{label}</a>"
    )


def render_at_a_glance(
    sections: list[tuple[str, list[tuple[dict[str, object], list[str]]]]],
) -> list[str]:
    """One compact line per tag: italic label, then three-word RSS links."""
    lines: list[str] = []
    for tag, items in sections:
        slug = tag_section_id(tag)
        phrases = []
        for story, _extra in items:
            link = str(story.get("link") or story.get("url") or "").strip()
            phrases.append(glance_markdown(story.get("headline"), link, slug))
        lines.append(f"{glance_tag_label(tag)}: {', '.join(phrases)}")
    return lines


def unique_slug(headline: object, used: set[str]) -> str:
    """Return a slug that has not already been assigned in this brief."""
    base = slugify(headline)
    slug = base
    suffix = 2
    while slug in used:
        slug = f"{base}-{suffix}"
        suffix += 1
    used.add(slug)
    return slug


def group_stories_by_headline(
    stories: list[dict[str, object]],
) -> list[tuple[dict[str, object], list[str]]]:
    """Keep the first story; later exact-headline matches add unique sources."""
    groups: list[tuple[dict[str, object], list[str]]] = []
    index: dict[str, int] = {}
    for story in stories:
        key = normalize_headline(story.get("headline"))
        if key in index:
            primary, extra_sources = groups[index[key]]
            source = story.get("source")
            primary_source = primary.get("source")
            if (
                isinstance(source, str)
                and source
                and source != primary_source
                and source not in extra_sources
            ):
                extra_sources.append(source)
            continue
        index[key] = len(groups)
        groups.append((story, []))
    return groups


def render_headline_item(
    story: dict[str, object],
    extra_sources: list[str] | None = None,
) -> str:
    """RSS headline link, colored tag chips, optional also-covered-by. No Why It Matters."""
    headline = str(story.get("headline") or "").strip() or "(untitled)"
    link = str(story.get("link") or story.get("url") or "").strip()
    if link:
        source_link = f"[{headline}]({link})"
    else:
        source_link = f"**{headline}**"
    chips = tag_chips_html(story_tags(story))
    lead = f"- {source_link} {chips}".rstrip()
    lines = [lead]
    if extra_sources:
        lines.append(f"  also covered by [{', '.join(extra_sources)}]")
    return "\n".join(lines)


def render_story(
    story: dict[str, object],
    extra_sources: list[str] | None = None,
    slug: str | None = None,
) -> str:
    """Headline-only story line. ``slug`` is ignored (At a Glance uses RSS URLs)."""
    del slug
    return render_headline_item(story, extra_sources)


def grouped_sections(
    selected_run: dict[str, object],
) -> list[tuple[str, list[tuple[dict[str, object], list[str]]]]]:
    """One section per story: the highest-weight tag from config."""
    sections = {section: [] for section in SECTION_ORDER}
    for story in selected_run["stories"]:
        sections[section_for_story(story)].append(story)
    grouped = []
    for section in SECTION_ORDER:
        items = group_stories_by_headline(sections[section])
        if items:
            grouped.append((section, items))
    return grouped


def copy_from_run(selected_run: dict[str, object]) -> tuple[dict[str, str], str, list[str]]:
    """Read structured briefing copy, or JSON stored in ``macro_report``."""
    notes = selected_run.get("tag_notes")
    summary = selected_run.get("daily_summary")
    radar = selected_run.get("research_radar")
    if isinstance(notes, dict) and isinstance(summary, str) and summary.strip():
        cleaned_notes = {
            str(tag): text.strip()
            for tag, text in notes.items()
            if isinstance(tag, str) and isinstance(text, str) and text.strip()
        }
        radar_items = (
            [item.strip() for item in radar if isinstance(item, str) and item.strip()]
            if isinstance(radar, list)
            else []
        )
        return cleaned_notes, summary.strip(), radar_items

    macro = selected_run.get("macro_report")
    if isinstance(macro, str) and macro.strip():
        try:
            from summarize_stories import parse_briefing_copy

            return parse_briefing_copy(macro)
        except Exception:
            if not any(marker.lower() in macro.lower() for marker in PENDING_MARKERS):
                return {}, macro.strip(), []
    return {}, "", []


def render_tag_section(
    tag: str,
    items: list[tuple[dict[str, object], list[str]]],
    note: str | None,
) -> list[str]:
    lines = ["", tag_heading_markdown(tag), ""]
    for story, extra_sources in items:
        lines.append(render_headline_item(story, extra_sources))
    if note and note.strip():
        lines.extend(["", f"Why it might matter / pattern: {note.strip()}"])
    return lines


def render_daily_summary(summary: str, radar: list[str]) -> list[str]:
    if not summary and not radar:
        return []
    lines = ["", "## Daily Summary & Research Topics", ""]
    if summary:
        lines.append(summary)
    if radar:
        if summary:
            lines.append("")
        lines.append("Research topics to look into more")
        lines.append("")
        for index, topic in enumerate(radar, start=1):
            lines.append(f"{index}. {topic}")
    return lines


def render_brief(selected_run: dict[str, object], date_stem: str) -> str:
    """Render title, snapshot, glance, per-tag sections, then Daily Summary."""
    snapshot = selected_run.get("market_snapshot")
    lines = [
        f"# Looping... ({date_stem})",
        "",
        "Loop: AI Market Briefing. Selected public reporting, organized by topic. Links lead to the original source.",
        "",
        fetch_market.render_market_block(snapshot if isinstance(snapshot, dict) else None),
        "",
        "## At a Glance",
        "",
    ]

    notes, daily_summary, radar = copy_from_run(selected_run)
    sections = grouped_sections(selected_run)
    lines.extend(render_at_a_glance(sections))
    if sections:
        lines.extend(["", "---"])
    for section, items in sections:
        note = notes.get(section) if section != "Other" else None
        lines.extend(render_tag_section(section, items, note))
    summary_lines = render_daily_summary(daily_summary, radar)
    if summary_lines:
        lines.extend(["", "---"])
        lines.extend(summary_lines)
    briefing = "\n".join(lines) + "\n"
    for marker in PENDING_MARKERS:
        if marker.lower() in briefing.lower():
            briefing = re.sub(re.escape(marker), "", briefing, flags=re.I)
    if "Why It Matters:" in briefing:
        briefing = "\n".join(
            line for line in briefing.splitlines() if "Why It Matters:" not in line
        ) + "\n"
    return briefing


def save_brief(selected_run: dict[str, object], input_path: Path) -> Path:
    """Save a Markdown briefing beside other generated briefings."""
    BRIEFS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = BRIEFS_DIRECTORY / f"{input_path.stem}.md"
    output_path.write_text(
        render_brief(selected_run, input_path.stem), encoding="utf-8"
    )
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a topic-organized Loop: AI Market Briefing."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="Summarized or selected JSON file to render. Defaults to summarized, then selected.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_briefing_source()
    selected_run = load_selected_run(input_file)
    saved_file = save_brief(selected_run, input_file)
    print(f"Loop: wrote {len(selected_run['stories'])} stories.")
    print(f"Saved briefing to {saved_file}")
