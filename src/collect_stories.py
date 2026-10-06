"""Collect the latest items from the V2.5 public RSS feeds.

Run from the project folder:
    python3 src/collect_stories.py
"""

from datetime import date
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


SOURCES = [
    {
        "source": "Reuters AI",
        "url": "https://news.google.com/rss/search?q=site:reuters.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "source": "CNBC Tech & Markets",
        "url": "https://news.google.com/rss/search?q=site:cnbc.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "source": "AP News Policy",
        "url": "https://news.google.com/rss/search?q=site:apnews.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "source": "FT & WSJ Proxy",
        "url": "https://news.google.com/rss/search?q=(site:ft.com+OR+site:wsj.com)+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "source": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "source": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
    },
    {
        "source": "OpenAI News",
        "url": "https://openai.com/news/rss.xml",
    },
    {
        "source": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
    },
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIRECTORY = PROJECT_ROOT / "data" / "raw"


def plain_text(value: str) -> str:
    """Drop markup so a description can be stored and tagged as text."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(text.split())


def is_google_news_url(url: str) -> bool:
    """Return whether a link is a Google News redirect rather than a publisher page."""
    host = urlparse(url).netloc.lower()
    return host == "news.google.com" or host.endswith(".news.google.com")


def publisher_url_from_token(url: str) -> str | None:
    """Read a publisher URL embedded in a Google News article token, if present."""
    token = urlparse(url).path.rstrip("/").split("/")[-1]
    if not token:
        return None
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except Exception:
        return None
    text = raw.decode("utf-8", errors="ignore")
    for match in re.findall(r"https?://[^\s\x00-\x1f\"'<>\\]+", text):
        host = urlparse(match).netloc.lower()
        if host and "google." not in host:
            return match.rstrip(".,)")
    return None


def resolve_publisher_url(url: str) -> str:
    """Return the publisher URL for a Google News redirect, or the original link."""
    if not isinstance(url, str) or not url.strip() or not is_google_news_url(url.strip()):
        return url
    decoded = publisher_url_from_token(url.strip())
    if decoded:
        return decoded
    try:
        request = Request(url.strip(), headers={"User-Agent": "AI-Market-Briefing/0.1"})
        with urlopen(request, timeout=15) as response:
            final = response.geturl()
    except Exception:
        return url
    if isinstance(final, str) and final and not is_google_news_url(final):
        return final
    return url


def item_description(item: ET.Element) -> str:
    """Read the RSS description, including encoded content when that is all a feed offers."""
    text = item.findtext("description") or ""
    if not text.strip():
        for child in item:
            if child.tag.endswith("encoded") and child.text:
                text = child.text
                break
    return plain_text(text)


def fetch_feed(feed: dict[str, str]) -> list[dict[str, str]]:
    """Download one RSS feed and return its stories in our shared format."""
    request = Request(feed["url"], headers={"User-Agent": "AI-Market-Briefing/0.1"})

    with urlopen(request, timeout=20) as response:
        rss = ET.fromstring(response.read())

    stories = []
    for item in rss.findall("./channel/item"):
        link = item.findtext("link", default="").strip()
        stories.append(
            {
                "headline": item.findtext("title", default="").strip(),
                "source": feed["source"],
                "link": resolve_publisher_url(link),
                "published_at": item.findtext("pubDate", default="").strip(),
                "description": item_description(item),
            }
        )

    return stories


def collect_stories() -> tuple[list[dict[str, str]], list[str]]:
    """Collect all available feeds without letting one failed feed stop the run."""
    stories = []
    failed_sources = []

    for feed in SOURCES:
        try:
            stories.extend(fetch_feed(feed))
        except Exception:
            failed_sources.append(feed["source"])

    return stories, failed_sources


def save_run(stories: list[dict[str, str]], failed_sources: list[str]) -> Path:
    """Save the raw source evidence and quiet run record as JSON."""
    RAW_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = RAW_DATA_DIRECTORY / f"{date.today().isoformat()}.json"
    output = {"stories": stories, "failed_sources": failed_sources}
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    stories, failed_sources = collect_stories()
    saved_file = save_run(stories, failed_sources)
    print(f"Collected {len(stories)} stories.")
    print(f"Saved raw data to {saved_file}")
