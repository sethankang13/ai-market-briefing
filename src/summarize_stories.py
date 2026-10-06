"""Add AI "Why It Matters" summaries to a selected story run.

Run from the project folder:
    python3 src/summarize_stories.py

Provider order:
1. Gemini ``gemini-3.6-flash`` when ``GEMINI_API_KEY`` is set.
2. OpenAI ``gpt-4o-mini`` when Gemini is missing or fails and ``OPENAI_API_KEY`` is set.
3. Otherwise a mock placeholder: ``[AI Summary Pending: <Headline>]``.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELECTED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "selected"
SUMMARIZED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "summarized"
GEMINI_MODEL = "gemini-3.6-flash"
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
SYSTEM_PROMPT = (
    "You write one or two sentences of Why It Matters for a personal market briefing. "
    "Use only the supplied headline, source, topics, and selection reason. "
    "Do not invent facts. Treat market-impact or causal language as interpretation, "
    "not established fact. Return plain text only."
)


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


def mock_summary(headline: str) -> str:
    """Return a visible placeholder when no usable API key is available."""
    return f"[AI Summary Pending: {headline}]"


def story_prompt(story: dict[str, object]) -> str:
    """Build the user prompt from source-supported selected-story fields."""
    topics = ", ".join(story.get("topics") or [])
    reason = story.get("selection_reason") or "Not provided."
    return (
        f"Headline: {story['headline']}\n"
        f"Source: {story.get('source', 'Unknown')}\n"
        f"Topics: {topics or 'none'}\n"
        f"Selection reason: {reason}\n\n"
        "Write Why It Matters."
    )


def _post_json(
    url: str, payload: dict[str, object], headers: dict[str, str], timeout: int = 30
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
    """Return user-facing summary text, skipping model thought parts."""
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


def summarize_with_gemini(story: dict[str, object], api_key: str) -> str:
    """Ask Gemini flash for a Why It Matters sentence."""
    payload = {
        "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{story_prompt(story)}"}]}],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    data = _post_json(
        GEMINI_URL,
        payload,
        {"x-goog-api-key": api_key},
    )
    return visible_gemini_text(data)


def summarize_with_openai(story: dict[str, object], api_key: str) -> str:
    """Ask OpenAI gpt-4o-mini for a Why It Matters sentence."""
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "max_tokens": 180,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": story_prompt(story)},
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
    text = text.strip()
    if not text:
        raise ValueError("OpenAI returned an empty summary.")
    return text


def summarize_story(story: dict[str, object]) -> tuple[str, str]:
    """Return ``(summary, provider)`` using Gemini, OpenAI, or the mock."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        try:
            return summarize_with_gemini(story, gemini_key), "gemini"
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            if openai_key:
                try:
                    return summarize_with_openai(story, openai_key), "openai"
                except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                    return mock_summary(story["headline"]), "mock"
            return mock_summary(story["headline"]), "mock"

    if openai_key:
        try:
            return summarize_with_openai(story, openai_key), "openai"
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            return mock_summary(story["headline"]), "mock"

    return mock_summary(story["headline"]), "mock"


def summarize_stories(stories: list[dict[str, object]]) -> tuple[list[dict[str, object]], str]:
    """Copy each selected story and attach ``ai_summary`` without mutating input."""
    summarized = []
    providers = []
    for story in stories:
        summary, provider = summarize_story(story)
        providers.append(provider)
        summarized.append({**story, "ai_summary": summary})
    if "gemini" in providers:
        used = "gemini"
    elif "openai" in providers:
        used = "openai"
    else:
        used = "mock"
    return summarized, used


def save_summarized_run(selected_run: dict[str, object], input_path: Path) -> Path:
    """Create ``data/summarized`` if needed, then write the dated JSON file."""
    os.makedirs("data/summarized", exist_ok=True)
    SUMMARIZED_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stories, provider = summarize_stories(selected_run["stories"])
    output = {
        "selected_run": input_path.name,
        "failed_sources": selected_run.get("failed_sources", []),
        "summarizer": provider,
        "stories": stories,
    }
    output_path = SUMMARIZED_DATA_DIRECTORY / input_path.name
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add AI Why It Matters summaries to a selected story run."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="Selected JSON file to summarize. Defaults to the latest data/selected file.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_selected_run()
    selected_run = load_selected_run(input_file)
    saved_file = save_summarized_run(selected_run, input_file)
    print(f"Summarized {len(selected_run['stories'])} stories.")
    print(f"Saved summarized data to {saved_file}")
