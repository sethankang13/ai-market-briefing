"""Write one run-level briefing copy: per-tag notes, daily summary, research radar.

Run from the project folder:
    python3 src/summarize_stories.py
    python3 src/summarize_stories.py --mock

Live input is today's selected RSS headlines and snippets, grouped by
taxonomy tag, plus the last 14 days of stored briefing records from
``data/loop.db``. There is one Gemini Flash completion per run. The
existing model cascade is used only when the first model returns HTTP 429
(or another retryable error): still one successful completion, not one
call per story.

Article HTML extraction lives in ``archived_article_summarizer.py`` and is
not used here.

``--mock`` writes deterministic per-tag notes and a daily summary and does
not call a model or the network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

import db
from config_loader import load_config
from tag_stories import TAG_LABELS, primary_tag


_CONFIG = load_config()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
SUMMARIZED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "summarized"
GEMINI_MODELS = tuple(_CONFIG["models"]["gemini"])
GEMINI_MODEL = GEMINI_MODELS[0]
GEMINI_RETRY_ATTEMPTS = 3
OPENAI_MODEL = str(_CONFIG["models"]["openai_fallback"])
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
PENDING_MARKERS = (
    "AI Summary Pending",
    "AI Headline Pending",
    "AI headline pending",
    "AI Summary goes HERE",
)
SYSTEM_PROMPT = (
    "You write Loop: AI Market Briefing's daily copy from RSS headlines, "
    "native feed snippets, and the last 14 days of stored briefing records. "
    "Do not claim you read full articles. Do not invent facts that are not "
    "supported by the supplied headlines, snippets, or history. Label "
    "market-impact or causal language as interpretation. "
    "Return JSON only (no Markdown wrapper) with this shape:\n"
    '{"tag_notes": {"Tag-Name": "one paragraph for that tag"}, '
    '"daily_summary": "what happened today across all headlines and what it '
    'could mean", "research_radar": ["topic 1", "topic 2", "topic 3"]}\n'
    "tag_notes: one paragraph per taxonomy tag that has at least one of "
    "today's selected headlines. Use today's headlines in that tag plus "
    "the 14-day history for that tag. Do not write a per-story note, "
    "per-story Why It Matters, or a tags line. "
    "daily_summary: what happened today across all headlines, and what it "
    "could mean. research_radar: 3-5 high-impact topics worth manual "
    "follow-up. Do NOT wrap key figures, quotes, entity names, or phrases "
    "in backticks. Write plain unformatted executive text without inline "
    "code blocks. Never write pending-placeholder copy such as "
    '"AI Summary Pending" or "AI Headline Pending".'
)


class SummarizationError(Exception):
    """Every live model attempt failed. Do not write pending placeholders."""


class BriefingCopy(NamedTuple):
    """Run-level copy: one note per tag, a daily summary, and research topics."""

    tag_notes: dict[str, str]
    daily_summary: str
    research_radar: tuple[str, ...]
    provider: str

    @property
    def macro_report(self) -> str:
        """JSON payload persisted on the summarized run and in loop.db."""
        return serialize_briefing_copy(
            self.tag_notes, self.daily_summary, list(self.research_radar)
        )


# Older tests and persist_step still refer to MacroCopy / macro_report.
MacroCopy = BriefingCopy


def serialize_briefing_copy(
    tag_notes: dict[str, str],
    daily_summary: str,
    research_radar: list[str],
) -> str:
    return json.dumps(
        {
            "tag_notes": tag_notes,
            "daily_summary": daily_summary,
            "research_radar": research_radar,
        },
        indent=2,
    )


def reject_pending(text: str) -> None:
    lowered = text.lower()
    for marker in PENDING_MARKERS:
        if marker.lower() in lowered:
            raise ValueError("Model response used a pending placeholder.")


def story_tag_labels(story: dict[str, object]) -> list[str]:
    """Return assigned taxonomy tags in config order."""
    labels = story.get("tags")
    if not isinstance(labels, list):
        labels = story.get("topics") or []
    assigned = {label for label in labels if isinstance(label, str) and label}
    return [tag for tag in TAG_LABELS if tag in assigned]


def tags_with_stories(stories: list[dict[str, object]]) -> list[str]:
    """Tags that own a brief section: each story counts once, by highest weight."""
    present: set[str] = set()
    for story in stories:
        chosen = primary_tag(story_tag_labels(story))
        if chosen:
            present.add(chosen)
    return [tag for tag in TAG_LABELS if tag in present]


def history_tag_labels(row: dict[str, object]) -> list[str]:
    labels = row.get("tags")
    if isinstance(labels, str):
        try:
            parsed = json.loads(labels)
            labels = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            labels = []
    if not isinstance(labels, list):
        labels = []
    assigned = {label for label in labels if isinstance(label, str) and label}
    return [tag for tag in TAG_LABELS if tag in assigned]


def latest_selected_run(
    selected_data_directory: Path = SELECTED_DATA_DIRECTORY,
) -> Path:
    """Return the newest selected run, or explain why one cannot be found."""
    selected_runs = sorted(selected_data_directory.glob("*.json"))
    if not selected_runs:
        raise FileNotFoundError(
            f"No selected story runs found in {selected_data_directory}. "
            "Run select_stories.py first."
        )
    return selected_runs[-1]


def load_selected_run(input_path: Path) -> dict[str, object]:
    """Load one selected run and make sure it has a story list."""
    selected_run = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(selected_run, dict) or not isinstance(
        selected_run.get("stories"), list
    ):
        raise ValueError(f"{input_path} does not contain a 'stories' list.")
    return selected_run


def mock_briefing_copy(
    stories: list[dict[str, object]],
    history: list[dict[str, object]],
) -> BriefingCopy:
    """Deterministic offline copy used only with ``--mock``."""
    headlines = [
        str(story.get("headline") or "(untitled)") for story in stories
    ]
    listed = "; ".join(headlines) if headlines else "(no selected headlines)"
    tag_notes = {}
    for tag in tags_with_stories(stories):
        today = [
            str(story.get("headline") or "(untitled)")
            for story in stories
            if tag in story_tag_labels(story)
        ]
        prior = sum(1 for row in history if tag in history_tag_labels(row))
        tag_notes[tag] = (
            f"Mock pattern for #{tag}: today's headlines ({'; '.join(today)}) "
            f"read against {prior} stored {tag} records from the last 14 days."
        )
    radar = (
        "Mock follow-up on the densest selected tag cluster.",
        "Mock follow-up on a headline that repeats in stored history.",
        "Mock follow-up on a regulatory or market split in today's set.",
    )
    return BriefingCopy(
        tag_notes=tag_notes,
        daily_summary=(
            f"Mock daily summary of what happened today: {listed}. "
            f"Checked against {len(history)} stored briefing records "
            "from the last 14 days."
        ),
        research_radar=radar,
        provider="mock",
    )


def mock_macro_report(
    stories: list[dict[str, object]],
    history: list[dict[str, object]],
) -> str:
    """JSON string of mock per-tag notes and daily summary."""
    return mock_briefing_copy(stories, history).macro_report


def mock_summary(headline: str) -> str:
    """Backward-compatible mock line; the live brief uses mock_briefing_copy."""
    return f"Mock interpretation of {headline}."


def story_snippet(story: dict[str, object]) -> str:
    """Native RSS description/snippet only; never fetched article HTML."""
    for key in ("description", "full_text"):
        value = story.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def format_today_block(stories: list[dict[str, object]]) -> str:
    lines = ["TODAY'S SELECTED HEADLINES AND SNIPPETS, GROUPED BY TAG:"]
    if not stories:
        lines.append("(none)")
        return "\n".join(lines)
    grouped = False
    for tag in tags_with_stories(stories):
        grouped = True
        lines.append(f"[{tag}]")
        for story in stories:
            if tag not in story_tag_labels(story):
                continue
            snippet = story_snippet(story)
            lines.append(
                f"- {story.get('source', 'Unknown')} | {story.get('headline')} | "
                f"snippet: {snippet or '(none)'}"
            )
    untagged = [story for story in stories if not story_tag_labels(story)]
    if untagged:
        lines.append("[untagged]")
        for story in untagged:
            snippet = story_snippet(story)
            lines.append(
                f"- {story.get('source', 'Unknown')} | {story.get('headline')} | "
                f"snippet: {snippet or '(none)'}"
            )
            grouped = True
    if not grouped:
        lines.append("(none)")
    return "\n".join(lines)


def format_history_block(history: list[dict[str, object]]) -> str:
    lines = ["LAST 14 DAYS OF STORED BRIEFING RECORDS, GROUPED BY TAG:"]
    if not history:
        lines.append("(none; do not invent prior coverage)")
        return "\n".join(lines)
    any_tag = False
    for tag in TAG_LABELS:
        rows = [row for row in history if tag in history_tag_labels(row)]
        if not rows:
            continue
        any_tag = True
        lines.append(f"[{tag}]")
        for row in rows:
            snippet = ""
            for key in ("full_text", "description", "ai_summary"):
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    snippet = " ".join(value.split())[:400]
                    break
            lines.append(
                f"- {row.get('published_date') or ''} | {row.get('source') or 'Unknown'} | "
                f"{row.get('headline')} | snippet: {snippet or '(none)'}"
            )
    if not any_tag:
        lines.append("(none with taxonomy tags; do not invent prior coverage)")
    return "\n".join(lines)


def run_prompt(
    stories: list[dict[str, object]],
    history: list[dict[str, object]],
) -> str:
    """Build the single user prompt for this run."""
    expected = tags_with_stories(stories)
    return "\n\n".join(
        [
            "Write today's briefing copy from the material below.",
            f"Tags that must appear in tag_notes: {', '.join(expected) or '(none)'}.",
            format_today_block(stories),
            format_history_block(history),
            "Return JSON only with tag_notes, daily_summary, and research_radar.",
        ]
    )


def _post_json(
    url: str, payload: dict[str, object], headers: dict[str, str], timeout: int = 60
) -> dict[str, object]:
    """POST JSON and return the decoded object. Isolated so tests can mock it."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def visible_gemini_text(data: dict[str, object]) -> str:
    """Return user-facing model text, skipping thought parts."""
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Gemini response did not contain summary text.") from error
    if not isinstance(parts, list):
        raise ValueError("Gemini response did not contain summary text.")
    visible = []
    for part in parts:
        if not isinstance(part, dict) or part.get("thought"):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            visible.append(text.strip())
    text = "\n".join(visible).strip()
    if not text:
        raise ValueError("Gemini response did not contain summary text.")
    return text


def _radar_from_value(value: object) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        items = []
        for line in value.splitlines():
            cleaned = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip()
            if cleaned:
                items.append(cleaned)
        return items
    return []


def _notes_from_value(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    notes = {}
    for key, text in value.items():
        if not isinstance(key, str) or not key:
            continue
        if isinstance(text, str) and text.strip():
            notes[key] = text.strip()
    return notes


def parse_delimited_sections(text: str) -> tuple[dict[str, str], str, list[str]]:
    """Parse clearly delimited Markdown when the model skipped JSON."""
    notes: dict[str, str] = {}
    daily = ""
    radar: list[str] = []
    current = None
    chunks: dict[str, list[str]] = {}
    for line in text.splitlines():
        heading = re.match(r"^#{1,3}\s+(.*)$", line)
        if heading:
            title = heading.group(1).strip()
            if re.search(r"daily summary", title, re.I):
                current = "daily"
            elif re.search(r"research", title, re.I):
                current = "radar"
            else:
                tag = title.lstrip("#").strip()
                tag = re.sub(r"^Tag:\s*", "", tag, flags=re.I)
                current = tag
            chunks.setdefault(current, [])
            continue
        if current is None:
            continue
        chunks.setdefault(current, []).append(line)
    for key, lines in chunks.items():
        body = "\n".join(lines).strip()
        if not body or key is None:
            continue
        if key == "daily":
            daily = body
        elif key == "radar":
            radar = _radar_from_value(body)
        else:
            notes[key] = body
    return notes, daily, radar


def parse_briefing_copy(text: str) -> tuple[dict[str, str], str, list[str]]:
    """Accept JSON, or delimited sections with tag notes + daily summary + radar."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|markdown|md)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    reject_pending(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and (
            "daily_summary" in data or "tag_notes" in data or "research_radar" in data
        ):
            notes = _notes_from_value(data.get("tag_notes"))
            summary = data.get("daily_summary")
            daily = summary.strip() if isinstance(summary, str) else ""
            radar = _radar_from_value(data.get("research_radar"))
            if daily:
                return notes, daily, radar
    notes, daily, radar = parse_delimited_sections(cleaned)
    if not daily:
        raise ValueError("Model response missed a daily summary.")
    return notes, daily, radar


def parse_macro_report(text: str) -> str:
    """Normalize model text to the persisted JSON briefing payload."""
    notes, daily, radar = parse_briefing_copy(text)
    return serialize_briefing_copy(notes, daily, radar)


def fill_missing_tag_notes(
    notes: dict[str, str],
    stories: list[dict[str, object]],
) -> dict[str, str]:
    """Keep model notes; add a non-pending fallback for any missing today's tag."""
    filled = dict(notes)
    for tag in tags_with_stories(stories):
        existing = filled.get(tag)
        if isinstance(existing, str) and existing.strip():
            filled[tag] = existing.strip()
            continue
        headlines = [
            str(story.get("headline") or "(untitled)")
            for story in stories
            if tag in story_tag_labels(story)
        ]
        listed = "; ".join(headlines) if headlines else "(none)"
        filled[tag] = (
            f"Today's #{tag} headlines ({listed}) continue that tag's "
            "recent coverage; treat market-impact language as interpretation."
        )
    return filled


def gemini_url(model: str) -> str:
    return GEMINI_URL_TEMPLATE.format(model=model)


def generate_with_gemini(
    prompt: str,
    api_key: str,
    model: str = GEMINI_MODEL,
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    """Ask one Gemini flash model and return visible text (no JSON parse)."""
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"{system_prompt}\n\n{prompt}"
                    }
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    data = _post_json(
        gemini_url(model),
        payload,
        {"x-goog-api-key": api_key},
    )
    return visible_gemini_text(data)


def summarize_with_gemini(
    prompt: str,
    api_key: str,
    model: str = GEMINI_MODEL,
) -> str:
    """Ask one Gemini flash model for the run-level briefing JSON."""
    return parse_macro_report(generate_with_gemini(prompt, api_key, model=model))


def _retryable_http_error(error: urllib.error.HTTPError) -> bool:
    return error.code in {408, 429, 500, 502, 503, 504}


def _backoff_seconds(attempt: int) -> float:
    return float(2 ** (attempt - 1))


def _run_gemini_cascade(
    call_model,
    models: tuple[str, ...],
) -> tuple[object, str]:
    """Retry overloaded models, skip missing ones, then try the next id."""
    last_error: Exception | None = None
    for model in models:
        for attempt in range(1, GEMINI_RETRY_ATTEMPTS + 1):
            try:
                return call_model(model), model
            except urllib.error.HTTPError as error:
                last_error = error
                code = error.code
                try:
                    error.close()
                except Exception:
                    pass
                if code == 404:
                    break
                if _retryable_http_error(error) and attempt < GEMINI_RETRY_ATTEMPTS:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                last_error = error
                if attempt < GEMINI_RETRY_ATTEMPTS:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                break
            except (ValueError, KeyError) as error:
                last_error = error
                break
    raise SummarizationError(
        "All Gemini models failed: " + ", ".join(models)
    ) from last_error


def generate_with_gemini_cascade(
    prompt: str,
    api_key: str,
    models: tuple[str, ...] = GEMINI_MODELS,
    system_prompt: str = SYSTEM_PROMPT,
) -> tuple[str, str]:
    """Try Gemini models in order. 429/503 retry; 404 continues the cascade."""

    def call_model(model: str) -> str:
        return generate_with_gemini(
            prompt, api_key, model=model, system_prompt=system_prompt
        )

    return _run_gemini_cascade(call_model, models)


def summarize_with_gemini_cascade(
    prompt: str,
    api_key: str,
    models: tuple[str, ...] = GEMINI_MODELS,
) -> tuple[str, str]:
    """Try Gemini models in order. 429/503 retry; 404 continues the cascade."""

    def call_model(model: str) -> str:
        return summarize_with_gemini(prompt, api_key, model=model)

    return _run_gemini_cascade(call_model, models)


def summarize_with_openai(prompt: str, api_key: str) -> str:
    """Ask OpenAI gpt-4o-mini for the run-level briefing JSON."""
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    data = _post_json(
        OPENAI_URL,
        payload,
        {"Authorization": f"Bearer {api_key}"},
    )
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("OpenAI response did not contain summary text.") from error
    if not isinstance(text, str):
        raise ValueError("OpenAI response did not contain summary text.")
    return parse_macro_report(text)


def load_project_env(env_path: Path | None = None) -> None:
    """Load the project-root ``.env`` without overriding variables already set."""
    path = PROJECT_ROOT / ".env" if env_path is None else env_path
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[name] = value


def load_history(history: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    """Use supplied rows, or load the last 14 days from loop.db without inventing any."""
    if history is not None:
        return history
    try:
        return db.load_recent_stories()
    except Exception:
        return []


def briefing_from_payload(payload: str, stories: list[dict[str, object]], provider: str) -> BriefingCopy:
    notes, daily, radar = parse_briefing_copy(payload)
    notes = fill_missing_tag_notes(notes, stories)
    return BriefingCopy(
        tag_notes=notes,
        daily_summary=daily,
        research_radar=tuple(radar),
        provider=provider,
    )


def summarize_macro(
    stories: list[dict[str, object]],
    mock: bool = False,
    history: list[dict[str, object]] | None = None,
) -> BriefingCopy:
    """Return one briefing copy using the Gemini cascade, OpenAI, or ``--mock``."""
    records = load_history(history)
    if mock:
        return mock_briefing_copy(stories, records)
    load_project_env()
    prompt = run_prompt(stories, records)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        try:
            report, _model = summarize_with_gemini_cascade(prompt, gemini_key)
            return briefing_from_payload(report, stories, "gemini")
        except SummarizationError:
            if not openai_key:
                raise

    if openai_key:
        try:
            report = summarize_with_openai(prompt, openai_key)
            return briefing_from_payload(report, stories, "openai")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError) as error:
            raise SummarizationError("OpenAI summarization failed.") from error

    raise SummarizationError(
        "No Gemini or OpenAI API key is set. Pass --mock for offline copy."
    )


def summarize_stories(
    stories: list[dict[str, object]],
    mock: bool = False,
    history: list[dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], str, str]:
    """Copy selected stories and attach run-level copy. Does not mutate input."""
    result = summarize_macro(stories, mock=mock, history=history)
    copied = [{**story} for story in stories]
    return copied, result.provider, result.macro_report


def save_summarized_run(
    selected_run: dict[str, object],
    input_path: Path,
    mock: bool = False,
    history: list[dict[str, object]] | None = None,
) -> Path:
    """Create ``data/summarized`` if needed, then write the dated JSON file."""
    os.makedirs("data/summarized", exist_ok=True)
    SUMMARIZED_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    result = summarize_macro(selected_run["stories"], mock=mock, history=history)
    stories = [{**story} for story in selected_run["stories"]]
    output = {
        "selected_run": input_path.name,
        "failed_sources": selected_run.get("failed_sources", []),
        "summarizer": result.provider,
        "market_snapshot": selected_run.get("market_snapshot"),
        "tag_notes": result.tag_notes,
        "daily_summary": result.daily_summary,
        "research_radar": list(result.research_radar),
        "macro_report": result.macro_report,
        "stories": stories,
    }
    output_path = SUMMARIZED_DATA_DIRECTORY / input_path.name
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write per-tag notes and a daily summary for the selected run."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="Selected JSON file to summarize. Defaults to the latest data/selected file.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Write offline mock per-tag notes and daily summary; do not call Gemini or OpenAI.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_selected_run()
    selected_run = load_selected_run(input_file)
    saved_file = save_summarized_run(selected_run, input_file, mock=arguments.mock)
    print(f"Loop: wrote briefing copy for {len(selected_run['stories'])} stories.")
    print(f"Saved summarized data to {saved_file}")
