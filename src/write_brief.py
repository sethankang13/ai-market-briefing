"""Render a readable local Loop briefing from a summarized or selected story run.

Daily files use ``# Looping... (YYYY-MM-DD)``. Historical reports are rendered
separately by ``write_the_loop.py`` as ``# The Loop``.

Run from the project folder:
    python3 src/write_brief.py
"""

import argparse
import json
import re
from pathlib import Path

import fetch_market
from config_loader import load_config, project_path
from tag_stories import TAG_LABELS


_CONFIG = load_config()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARIZED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "summarized"
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
BRIEFS_DIRECTORY = project_path(_CONFIG["pipeline"]["output_dir"])
SECTION_ORDER = TAG_LABELS + ("Other",)


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
    """Return assigned tags, ignoring a missing or non-list value."""
    tags = story.get("tags")
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, str) and tag]


def section_for_story(story: dict[str, object]) -> str:
    """Choose one section from the first assigned tag in the V2.5 label order."""
    tags = story_tags(story)
    for label in TAG_LABELS:
        if label in tags:
            return label
    return "Other"


def tags_line(story: dict[str, object]) -> str:
    """Render the italic tag line under the story title."""
    hashes = " ".join(f"#{tag}" for tag in story_tags(story))
    if hashes:
        return f"  *Tags: {hashes}*  "
    return "  *Tags:*  "


def why_it_matters(story: dict[str, object]) -> str | None:
    """Use the stored AI summary. Never emit pending placeholders."""
    summary = story.get("ai_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return None


def normalize_headline(headline: object) -> str:
    """Collapse whitespace and lowercase so exact headlines group together."""
    return " ".join(str(headline or "").lower().split())


def slugify(headline: object) -> str:
    """Turn an RSS headline into a stable Markdown fragment id."""
    lowered = str(headline or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "story"


def glance_markdown(headline: object, url: object, slug: str) -> str:
    """At a Glance: RSS headline as a hyperlink, with a slug fallback."""
    title = str(headline or "").strip() or "(untitled)"
    href = str(url or "").strip()
    if href:
        return f"- [{title}]({href})"
    return f"- [{title}](#{slug})"


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


def render_story(
    story: dict[str, object],
    extra_sources: list[str] | None = None,
    slug: str | None = None,
) -> str:
    """Lead with the original headline and link, then tags and why it matters."""
    source_link = f"[{story['headline']}]({story['link']})"
    summary = why_it_matters(story)
    lines = []
    if slug:
        lines.append(f'<a id="{slug}"></a>')
    lines.extend([f"- {source_link}  ", tags_line(story)])
    if extra_sources:
        lines.append(f"  also covered by [{', '.join(extra_sources)}]")
    if summary:
        lines.append(f"  Why It Matters: {summary}")
    return "\n".join(lines)


def grouped_sections(
    selected_run: dict[str, object],
) -> list[tuple[str, list[tuple[dict[str, object], list[str]]]]]:
    """Group stories by section, then collapse exact RSS headlines."""
    sections = {section: [] for section in SECTION_ORDER}
    for story in selected_run["stories"]:
        sections[section_for_story(story)].append(story)
    grouped = []
    for section in SECTION_ORDER:
        items = group_stories_by_headline(sections[section])
        if items:
            grouped.append((section, items))
    return grouped


def render_brief(selected_run: dict[str, object], date_stem: str) -> str:
    """Render the selected stories as a concise, topic-organized Markdown brief."""
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

    used_slugs: set[str] = set()
    glance: list[tuple[str, str, str]] = []
    detail_blocks: list[str] = []
    for section, items in grouped_sections(selected_run):
        assigned = []
        for story, extra_sources in items:
            slug = unique_slug(story.get("headline"), used_slugs)
            link = str(story.get("link") or story.get("url") or "").strip()
            glance.append((str(story["headline"]), slug, link))
            assigned.append(render_story(story, extra_sources, slug))
        detail_blocks.extend(["", f"## {section}", "", *assigned])

    for headline, slug, link in glance:
        lines.append(glance_markdown(headline, link, slug))

    lines.extend(detail_blocks)
    return "\n".join(lines) + "\n"


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
