"""Write one headline-based macro report per briefing run.

Run from the project folder:
    python3 src/summarize_stories.py
    python3 src/summarize_stories.py --mock

Live input is today's selected RSS headlines and snippets plus the last 14
days of stored briefing records from ``data/loop.db``. There is one Gemini
Flash completion per run. The existing model cascade is used only when the
first model returns HTTP 429 (or another retryable error): still one
successful completion, not one call per story.

Article HTML extraction lives in ``archived_article_summarizer.py`` and is
not used here.

``--mock`` writes deterministic placeholder sections and does not call a
model or the network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

import db
from config_loader import load_config


_CONFIG = load_config()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
SUMMARIZED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "summarized"
GEMINI_MODELS = tuple(_CONFIG["models"]["gemini"])
GEMINI_MODEL = GEMINI_MODELS[0]
OPENAI_MODEL = str(_CONFIG["models"]["openai_fallback"])
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
PENDING_MARKERS = (
    "AI Summary Pending",
    "AI Headline Pending",
    "AI Summary goes HERE",
)
REQUIRED_HEADINGS = (
    "# The Loop: Macro Landscape",
    "## Pattern Analysis & Signal Drift",
    "## Research Radar",
)
SYSTEM_PROMPT = (
    "You write Loop: AI Market Briefing's daily macro report from RSS "
    "headlines, native feed snippets, and the last 14 days of stored "
    "briefing records. Do not claim you read full articles. Do not invent "
    "facts that are not supported by the supplied headlines, snippets, or "
    "history. Label market-impact or causal language as interpretation. "
    "Return Markdown only, with exactly these headings in this order:\n"
    "# The Loop: Macro Landscape\n"
    "## Pattern Analysis & Signal Drift\n"
    "## Research Radar\n"
    "Macro Landscape: primary market, tech, and regulatory clusters from "
    "today's headlines. Pattern Analysis: how today connects to, accelerates, "
    "or contradicts the last 14 days. Research Radar: 3-5 high-impact topics "
    "worth manual follow-up. Never write pending-placeholder copy."
)


class SummarizationError(Exception):
    """Every live model attempt failed. Do not write pending placeholders."""


class MacroCopy(NamedTuple):
    """One run-level macro report and the provider that produced it."""

    macro_report: str
    provider: str


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


def mock_macro_report(
    stories: list[dict[str, object]],
    history: list[dict[str, object]],
) -> str:
    """Deterministic offline sections used only with ``--mock``."""
    headlines = [
        str(story.get("headline") or "(untitled)") for story in stories
    ]
    listed = "; ".join(headlines) if headlines else "(no selected headlines)"
    return (
        "# The Loop: Macro Landscape\n\n"
        f"Mock landscape clustered from: {listed}.\n\n"
        "## Pattern Analysis & Signal Drift\n\n"
        f"Mock drift check against {len(history)} stored briefing records "
        "from the last 14 days.\n\n"
        "## Research Radar\n\n"
        "1. Mock follow-up on the densest selected tag cluster.\n"
        "2. Mock follow-up on a headline that repeats in stored history.\n"
        "3. Mock follow-up on a regulatory or market split in today's set.\n"
    )


def mock_summary(headline: str) -> str:
    """Backward-compatible mock line; the live brief uses mock_macro_report."""
    return f"Mock interpretation of {headline}."


def story_snippet(story: dict[str, object]) -> str:
    """Native RSS description/snippet only; never fetched article HTML."""
    for key in ("description", "full_text"):
        value = story.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def format_today_block(stories: list[dict[str, object]]) -> str:
    lines = ["TODAY'S SELECTED HEADLINES AND SNIPPETS:"]
    if not stories:
        lines.append("(none)")
        return "\n".join(lines)
    for story in stories:
        labels = story.get("tags")
        if not isinstance(labels, list):
            labels = story.get("topics") or []
        tags = ", ".join(label for label in labels if isinstance(label, str))
        snippet = story_snippet(story)
        lines.append(
            f"- {story.get('source', 'Unknown')} | {story.get('headline')} | "
            f"tags: {tags or 'none'} | snippet: {snippet or '(none)'}"
        )
    return "\n".join(lines)


def format_history_block(history: list[dict[str, object]]) -> str:
    lines = ["LAST 14 DAYS OF STORED BRIEFING RECORDS:"]
    if not history:
        lines.append("(none; do not invent prior coverage)")
        return "\n".join(lines)
    for row in history:
        labels = row.get("tags")
        if isinstance(labels, str):
            try:
                parsed = json.loads(labels)
                labels = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                labels = []
        if not isinstance(labels, list):
            labels = []
        tags = ", ".join(label for label in labels if isinstance(label, str))
        snippet = ""
        for key in ("full_text", "description", "ai_summary"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                snippet = " ".join(value.split())[:400]
                break
        lines.append(
            f"- {row.get('published_date') or ''} | {row.get('source') or 'Unknown'} | "
            f"{row.get('headline')} | tags: {tags or 'none'} | "
            f"snippet: {snippet or '(none)'}"
        )
    return "\n".join(lines)


def run_prompt(
    stories: list[dict[str, object]],
    history: list[dict[str, object]],
) -> str:
    """Build the single user prompt for this run."""
    return "\n\n".join(
        [
            "Write today's macro report from the material below.",
            format_today_block(stories),
            format_history_block(history),
            "Return Markdown with the three required headings and no JSON wrapper.",
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


def parse_macro_report(text: str) -> str:
    """Accept Markdown, or JSON with a ``macro_report`` field."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|markdown|md)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            report = data.get("macro_report")
            if isinstance(report, str) and report.strip():
                cleaned = report.strip()
    for marker in PENDING_MARKERS:
        if marker in cleaned:
            raise ValueError("Model response used a pending placeholder.")
    for heading in REQUIRED_HEADINGS:
        if heading not in cleaned:
            raise ValueError("Model response missed a required macro heading.")
    return cleaned


def gemini_url(model: str) -> str:
    return GEMINI_URL_TEMPLATE.format(model=model)


def summarize_with_gemini(
    prompt: str,
    api_key: str,
    model: str = GEMINI_MODEL,
) -> str:
    """Ask one Gemini flash model for the run-level macro report."""
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"{SYSTEM_PROMPT}\n\n{prompt}"
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
    return parse_macro_report(visible_gemini_text(data))


def _retryable_http_error(error: urllib.error.HTTPError) -> bool:
    return error.code in {404, 408, 429, 500, 502, 503, 504}


def summarize_with_gemini_cascade(
    prompt: str,
    api_key: str,
    models: tuple[str, ...] = GEMINI_MODELS,
) -> tuple[str, str]:
    """Try Gemini models in order. 429/connection/404 errors continue the cascade."""
    last_error: Exception | None = None
    for model in models:
        try:
            report = summarize_with_gemini(prompt, api_key, model=model)
            return report, model
        except urllib.error.HTTPError as error:
            last_error = error
            try:
                error.close()
            except Exception:
                pass
            if _retryable_http_error(error):
                continue
            continue
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            ValueError,
            KeyError,
        ) as error:
            last_error = error
            continue
    raise SummarizationError(
        "All Gemini models failed: " + ", ".join(models)
    ) from last_error


def summarize_with_openai(prompt: str, api_key: str) -> str:
    """Ask OpenAI gpt-4o-mini for the run-level macro report."""
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


def summarize_macro(
    stories: list[dict[str, object]],
    mock: bool = False,
    history: list[dict[str, object]] | None = None,
) -> MacroCopy:
    """Return one macro report using the Gemini cascade, OpenAI, or ``--mock``."""
    records = load_history(history)
    if mock:
        return MacroCopy(mock_macro_report(stories, records), "mock")
    load_project_env()
    prompt = run_prompt(stories, records)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        try:
            report, _model = summarize_with_gemini_cascade(prompt, gemini_key)
            return MacroCopy(report, "gemini")
        except SummarizationError:
            if not openai_key:
                raise

    if openai_key:
        try:
            report = summarize_with_openai(prompt, openai_key)
            return MacroCopy(report, "openai")
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
    """Copy selected stories and attach a run-level macro report. Does not mutate input."""
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
    stories, provider, macro_report = summarize_stories(
        selected_run["stories"], mock=mock, history=history
    )
    output = {
        "selected_run": input_path.name,
        "failed_sources": selected_run.get("failed_sources", []),
        "summarizer": provider,
        "market_snapshot": selected_run.get("market_snapshot"),
        "macro_report": macro_report,
        "stories": stories,
    }
    output_path = SUMMARIZED_DATA_DIRECTORY / input_path.name
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write one headline-based macro report for the selected run."
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
        help="Write offline mock macro sections and do not call Gemini or OpenAI.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_selected_run()
    selected_run = load_selected_run(input_file)
    saved_file = save_summarized_run(selected_run, input_file, mock=arguments.mock)
    print(f"Loop: wrote macro report for {len(selected_run['stories'])} stories.")
    print(f"Saved summarized data to {saved_file}")
