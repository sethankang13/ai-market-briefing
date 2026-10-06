"""Add AI headlines and Why It Matters summaries from article text.

Run from the project folder:
    python3 src/summarize_stories.py

Provider order:
1. Gemini ``gemini-3.6-flash`` when ``GEMINI_API_KEY`` is set.
2. OpenAI ``gpt-4o-mini`` when Gemini is missing or fails and ``OPENAI_API_KEY`` is set.
3. Otherwise pending placeholders for the headline and summary.

Each story's ``link`` is fetched with the standard library. Readable article text
is capped before it is sent. If the fetch or extract fails, the model sees only
the headline fields and the story records that the article was not read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple


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
MAX_ARTICLE_CHARS = 12000
MIN_ARTICLE_CHARS = 80
ARTICLE_NOT_READ = "Article was not read."
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "form"}
SYSTEM_PROMPT = (
    "You write a short why-it-matters headline and one or two sentences for a personal "
    "market briefing. Use only the supplied article text when it is present. "
    "If the article was not read, use only the headline, source, tags, and selection "
    "reason, and do not pretend the page was analyzed. Do not invent facts. "
    "Label market-impact or causal language as interpretation, not established fact. "
    'Return JSON only: {"ai_headline": "...", "ai_summary": "..."}.'
)


class ModelCopy(NamedTuple):
    """Headline, summary, provider, and whether the article text was read."""

    ai_headline: str
    ai_summary: str
    provider: str
    article_read: bool


class ArticleTextParser(HTMLParser):
    """Collect visible text, preferring ``article`` and then ``main``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.main_depth = 0
        self.in_body = False
        self.article_parts: list[str] = []
        self.main_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "body":
            self.in_body = True
        elif tag == "article":
            self.article_depth += 1
        elif tag == "main":
            self.main_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "body":
            self.in_body = False
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1
        elif tag == "main" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self.article_depth:
            self.article_parts.append(text)
        elif self.main_depth:
            self.main_parts.append(text)
        elif self.in_body:
            self.body_parts.append(text)

    @property
    def article_text(self) -> str:
        return "\n".join(self.article_parts).strip()

    @property
    def main_text(self) -> str:
        return "\n".join(self.main_parts).strip()

    @property
    def body_text(self) -> str:
        return "\n".join(self.body_parts).strip()


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


def mock_headline(headline: str) -> str:
    """Return a visible headline placeholder when no model copy is available."""
    return f"[AI Headline Pending: {headline}]"


def mock_summary(headline: str) -> str:
    """Return a visible summary placeholder when no model copy is available."""
    return f"[AI Summary Pending: {headline}]"


def extract_article_text(html: str) -> str:
    """Return readable text from HTML, preferring the article element."""
    parser = ArticleTextParser()
    parser.feed(html)
    parser.close()
    return parser.article_text or parser.main_text or parser.body_text


def cap_article_text(text: str) -> str:
    """Limit how much article text is sent to the model."""
    if len(text) <= MAX_ARTICLE_CHARS:
        return text
    return text[:MAX_ARTICLE_CHARS].rstrip() + "\n[Article text truncated]"


def fetch_html(url: str) -> str:
    """Download one article page. Isolated so tests can mock it."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AI-Market-Briefing/0.1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def read_article(url: object) -> tuple[str | None, bool]:
    """Fetch and extract article text. Failure means the article was not read."""
    if not isinstance(url, str) or not url.strip():
        return None, False
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, False
    article_url = url.strip()
    if "news.google.com" in parsed.netloc.lower():
        from collect_stories import resolve_publisher_url

        article_url = resolve_publisher_url(article_url)
    try:
        text = extract_article_text(fetch_html(article_url))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None, False
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < MIN_ARTICLE_CHARS:
        return None, False
    return cap_article_text(text), True


def story_prompt(story: dict[str, object], article_text: str | None, article_read: bool) -> str:
    """Build the user prompt from the article when it was read, otherwise the headline."""
    labels = story.get("tags")
    if not isinstance(labels, list):
        labels = story.get("topics") or []
    tags = ", ".join(label for label in labels if isinstance(label, str))
    reason = story.get("selection_reason") or "Not provided."
    lines = [
        f"Headline: {story['headline']}",
        f"Source: {story.get('source', 'Unknown')}",
        f"Tags: {tags or 'none'}",
        f"Selection reason: {reason}",
    ]
    if article_read and article_text:
        lines.append(
            "The article text below was fetched from the source page. "
            "Base the headline and summary on that text."
        )
        lines.append(f"Article text:\n{article_text}")
    else:
        lines.append(
            "The article was not read. Use only the headline, source, tags, "
            "and selection reason. Do not claim the article was analyzed."
        )
    lines.append(
        'Return JSON: {"ai_headline": "short why-it-matters headline", '
        '"ai_summary": "one or two sentences"}.'
    )
    return "\n".join(lines)


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


def parse_model_fields(text: str) -> tuple[str, str]:
    """Read ``ai_headline`` and ``ai_summary`` from a model JSON response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Model response did not contain JSON fields.")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as error:
        raise ValueError("Model response did not contain JSON fields.") from error
    headline = data.get("ai_headline") if isinstance(data, dict) else None
    summary = data.get("ai_summary") if isinstance(data, dict) else None
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("Model response did not contain an AI headline.")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Model response did not contain summary text.")
    return " ".join(headline.split()), summary.strip()


def summarize_with_gemini(
    story: dict[str, object],
    api_key: str,
    article_text: str | None,
    article_read: bool,
) -> tuple[str, str]:
    """Ask Gemini flash for a why-it-matters headline and summary."""
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"{SYSTEM_PROMPT}\n\n"
                            f"{story_prompt(story, article_text, article_read)}"
                        )
                    }
                ]
            }
        ],
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
    return parse_model_fields(visible_gemini_text(data))


def summarize_with_openai(
    story: dict[str, object],
    api_key: str,
    article_text: str | None,
    article_read: bool,
) -> tuple[str, str]:
    """Ask OpenAI gpt-4o-mini for a why-it-matters headline and summary."""
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": story_prompt(story, article_text, article_read)},
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
    return parse_model_fields(text)


def _mock_copy(headline: str, article_read: bool) -> ModelCopy:
    return ModelCopy(mock_headline(headline), mock_summary(headline), "mock", article_read)


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


def summarize_story(story: dict[str, object], mock: bool = False) -> ModelCopy:
    """Return model copy using Gemini, OpenAI, or the offline mock.

    ``mock`` forces the pending placeholders and does not call Gemini or OpenAI,
    even when an API key is already loaded.
    """
    headline = story["headline"]
    if mock:
        return _mock_copy(str(headline), False)
    load_project_env()
    article_text, article_read = read_article(story.get("link"))
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        try:
            ai_headline, ai_summary = summarize_with_gemini(
                story, gemini_key, article_text, article_read
            )
            return ModelCopy(ai_headline, ai_summary, "gemini", article_read)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            if openai_key:
                try:
                    ai_headline, ai_summary = summarize_with_openai(
                        story, openai_key, article_text, article_read
                    )
                    return ModelCopy(ai_headline, ai_summary, "openai", article_read)
                except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                    return _mock_copy(headline, article_read)
            return _mock_copy(headline, article_read)

    if openai_key:
        try:
            ai_headline, ai_summary = summarize_with_openai(
                story, openai_key, article_text, article_read
            )
            return ModelCopy(ai_headline, ai_summary, "openai", article_read)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            return _mock_copy(headline, article_read)

    return _mock_copy(headline, article_read)


def summarize_stories(
    stories: list[dict[str, object]],
    mock: bool = False,
) -> tuple[list[dict[str, object]], str]:
    """Copy each selected story and attach model fields without mutating input."""
    summarized = []
    providers = []
    for story in stories:
        result = summarize_story(story, mock=mock)
        providers.append(result.provider)
        copied = {
            **story,
            "ai_headline": result.ai_headline,
            "ai_summary": result.ai_summary,
            "article_read": result.article_read,
        }
        if not result.article_read:
            copied["article_note"] = ARTICLE_NOT_READ
        summarized.append(copied)
    if "gemini" in providers:
        used = "gemini"
    elif "openai" in providers:
        used = "openai"
    else:
        used = "mock"
    return summarized, used


def save_summarized_run(
    selected_run: dict[str, object], input_path: Path, mock: bool = False
) -> Path:
    """Create ``data/summarized`` if needed, then write the dated JSON file."""
    os.makedirs("data/summarized", exist_ok=True)
    SUMMARIZED_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stories, provider = summarize_stories(selected_run["stories"], mock=mock)
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
        description="Add AI headlines and Why It Matters summaries from article text."
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
        help="Write offline pending summaries and do not call Gemini or OpenAI.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_selected_run()
    selected_run = load_selected_run(input_file)
    saved_file = save_summarized_run(selected_run, input_file, mock=arguments.mock)
    print(f"Summarized {len(selected_run['stories'])} stories.")
    print(f"Saved summarized data to {saved_file}")
