"""Add Why It Matters summaries from article text.

Run from the project folder:
    python3 src/summarize_stories.py
    python3 src/summarize_stories.py --mock

Provider order:
1. Gemini cascade ``gemini-3.8-flash`` → ``gemini-3.7-flash`` →
   ``gemini-3.6-flash`` → ``gemini-2.5-flash`` when ``GEMINI_API_KEY`` is set.
2. OpenAI ``gpt-4o-mini`` when Gemini is missing or the cascade fails and
   ``OPENAI_API_KEY`` is set.
3. Otherwise raise. Live output never stores pending placeholders.

``--mock`` writes offline mock copy and does not call a model.

Each story prefers RSS ``full_text``. Otherwise the page is fetched and the
body is extracted with trafilatura, BeautifulSoup, or the stdlib HTML parser.
The RSS/original ``headline`` is the story title. Gemini writes a dense
1–2 sentence ``ai_summary`` only.
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
MAX_ARTICLE_CHARS = 12000
MIN_ARTICLE_CHARS = 80
ARTICLE_NOT_READ = "Article was not read."
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "form"}
PENDING_MARKERS = (
    "AI Summary Pending",
    "AI Headline Pending",
    "AI Summary goes HERE",
)
SYSTEM_PROMPT = (
    "You write one or two dense Why It Matters sentences for Loop: AI Market "
    "Briefing. Do not rewrite the publisher headline. Use the supplied article "
    "body when it is present; do not summarize from the headline alone if body "
    "text is provided. If the article was not read, use only the headline, "
    "source, tags, and selection reason, and do not pretend the page was "
    "analyzed. Do not invent facts. Label market-impact or causal language as "
    "interpretation, not established fact. "
    'Return JSON only: {"ai_summary": "..."}.'
)


class SummarizationError(Exception):
    """Every live model attempt failed. Do not write pending placeholders."""


class ModelCopy(NamedTuple):
    """Summary, provider, and whether the article text was read."""

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


def mock_summary(headline: str) -> str:
    """Return offline mock copy used only with ``--mock``."""
    return f"Mock interpretation of {headline}."


def _stdlib_extract(html: str) -> str:
    parser = ArticleTextParser()
    parser.feed(html)
    parser.close()
    return parser.article_text or parser.main_text or parser.body_text


def extract_article_text(html: str) -> str:
    """Prefer ``article``/``main``, then trafilatura, then BeautifulSoup, then body."""
    parser = ArticleTextParser()
    parser.feed(html or "")
    parser.close()
    if parser.article_text or parser.main_text:
        return parser.article_text or parser.main_text
    try:
        import trafilatura

        extracted = trafilatura.extract(html)
        if isinstance(extracted, str) and extracted.strip():
            return extracted.strip()
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        node = soup.find("article") or soup.find("main") or soup.body or soup
        text = node.get_text("\n", strip=True)
        if text:
            return text
    except Exception:
        pass
    return parser.body_text


def cap_article_text(text: str) -> str:
    """Limit how much article text is sent to the model."""
    if len(text) <= MAX_ARTICLE_CHARS:
        return text
    return text[:MAX_ARTICLE_CHARS].rstrip() + "\n[Article text truncated]"


def fetch_html(url: str) -> str:
    """Download one article page. Isolated so tests can mock it."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Loop-AI-Market-Briefing/0.1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def usable_body(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(cleaned) < MIN_ARTICLE_CHARS:
        return None
    return cap_article_text(cleaned)


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
    body = usable_body(text)
    if body is None:
        return None, False
    return body, True


def story_body(story: dict[str, object]) -> tuple[str | None, bool]:
    """Prefer RSS full_text; otherwise fetch and extract the article page."""
    rss_body = usable_body(story.get("full_text"))
    if rss_body is not None:
        return rss_body, True
    return read_article(story.get("link"))


def story_prompt(story: dict[str, object], article_text: str | None, article_read: bool) -> str:
    """Build the user prompt from the article when it was read, otherwise the headline."""
    labels = story.get("tags")
    if not isinstance(labels, list):
        labels = story.get("topics") or []
    tags = ", ".join(label for label in labels if isinstance(label, str))
    reason = story.get("selection_reason") or "Not provided."
    lines = [
        f"Original headline: {story['headline']}",
        f"Source: {story.get('source', 'Unknown')}",
        f"Tags: {tags or 'none'}",
        f"Selection reason: {reason}",
        "Keep the original headline unchanged. Do not write a replacement headline.",
    ]
    if article_read and article_text:
        lines.append(
            "The article body below is available. Base ai_summary "
            "on that body, not on the headline alone."
        )
        lines.append(f"Article text:\n{article_text}")
    else:
        lines.append(
            "The article was not read. Use only the headline, source, tags, "
            "and selection reason. Do not claim the article was analyzed."
        )
    lines.append(
        'Return JSON: {"ai_summary": "one or two dense sentences"}.'
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


def parse_model_fields(text: str) -> str:
    """Read ``ai_summary`` from a model JSON response."""
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
    summary = data.get("ai_summary") if isinstance(data, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Model response did not contain summary text.")
    summary = summary.strip()
    for marker in PENDING_MARKERS:
        if marker in summary:
            raise ValueError("Model response used a pending placeholder.")
    return summary


def gemini_url(model: str) -> str:
    return GEMINI_URL_TEMPLATE.format(model=model)


def summarize_with_gemini(
    story: dict[str, object],
    api_key: str,
    article_text: str | None,
    article_read: bool,
    model: str = GEMINI_MODEL,
) -> str:
    """Ask one Gemini flash model for a Why It Matters summary."""
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
        gemini_url(model),
        payload,
        {"x-goog-api-key": api_key},
    )
    return parse_model_fields(visible_gemini_text(data))


def _retryable_http_error(error: urllib.error.HTTPError) -> bool:
    return error.code in {404, 408, 429, 500, 502, 503, 504}


def summarize_with_gemini_cascade(
    story: dict[str, object],
    api_key: str,
    article_text: str | None,
    article_read: bool,
    models: tuple[str, ...] = GEMINI_MODELS,
) -> tuple[str, str]:
    """Try Gemini models in order. 429/connection/404 errors continue the cascade."""
    last_error: Exception | None = None
    for model in models:
        try:
            summary = summarize_with_gemini(
                story, api_key, article_text, article_read, model=model
            )
            return summary, model
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


def summarize_with_openai(
    story: dict[str, object],
    api_key: str,
    article_text: str | None,
    article_read: bool,
) -> str:
    """Ask OpenAI gpt-4o-mini for a Why It Matters summary."""
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
    return ModelCopy(mock_summary(headline), "mock", article_read)


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
    """Return model copy using the Gemini cascade, OpenAI, or ``--mock``.

    ``mock`` writes mock copy and does not call Gemini or OpenAI, even when an
    API key is already loaded. Live runs raise ``SummarizationError`` instead of
    writing pending placeholders.
    """
    headline = str(story["headline"])
    if mock:
        rss_body = usable_body(story.get("full_text"))
        return _mock_copy(headline, rss_body is not None)
    load_project_env()
    article_text, article_read = story_body(story)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        try:
            ai_summary, _model = summarize_with_gemini_cascade(
                story, gemini_key, article_text, article_read
            )
            return ModelCopy(ai_summary, "gemini", article_read)
        except SummarizationError:
            if not openai_key:
                raise

    if openai_key:
        try:
            ai_summary = summarize_with_openai(
                story, openai_key, article_text, article_read
            )
            return ModelCopy(ai_summary, "openai", article_read)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError) as error:
            raise SummarizationError("OpenAI summarization failed.") from error

    raise SummarizationError(
        "No Gemini or OpenAI API key is set. Pass --mock for offline copy."
    )


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
        "market_snapshot": selected_run.get("market_snapshot"),
        "stories": stories,
    }
    output_path = SUMMARIZED_DATA_DIRECTORY / input_path.name
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add Why It Matters summaries from article text."
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
        help="Write offline mock summaries and do not call Gemini or OpenAI.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    input_file = arguments.input_file or latest_selected_run()
    selected_run = load_selected_run(input_file)
    saved_file = save_summarized_run(selected_run, input_file, mock=arguments.mock)
    print(f"Loop: summarized {len(selected_run['stories'])} stories.")
    print(f"Saved summarized data to {saved_file}")
