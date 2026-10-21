"""Collect the latest items from the V2.5 public RSS feeds.

Items older than 48 hours relative to the run timestamp are dropped.
When a feed includes RSS content/encoded, that HTML is stored as full_text.

Run from the project folder:
    python3 src/collect_stories.py
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import struct_time
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
MAX_AGE = timedelta(hours=48)
USER_AGENT = "Loop-AI-Market-Briefing/0.1"

try:
    import feedparser as feedparser_module
except ImportError:
    feedparser_module = None


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
        request = Request(url.strip(), headers={"User-Agent": USER_AGENT})
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


def item_full_text(item: ET.Element) -> str:
    """Return RSS content/encoded as plain text when the feed includes a body."""
    for child in item:
        if child.tag.endswith("encoded") and child.text and child.text.strip():
            return plain_text(child.text)
    content = item.find("content")
    if content is not None and content.text and content.text.strip():
        return plain_text(content.text)
    return ""


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def datetime_from_struct(parsed: object) -> datetime | None:
    """Convert feedparser published_parsed / updated_parsed tuples."""
    if parsed is None:
        return None
    if isinstance(parsed, struct_time):
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    if isinstance(parsed, tuple) and len(parsed) >= 6:
        try:
            return datetime(
                int(parsed[0]),
                int(parsed[1]),
                int(parsed[2]),
                int(parsed[3]),
                int(parsed[4]),
                int(parsed[5]),
                tzinfo=timezone.utc,
            )
        except (TypeError, ValueError):
            return None
    return None


def parse_rfc822(value: str) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        return as_utc(parsedate_to_datetime(value.strip()))
    except (TypeError, ValueError, IndexError):
        return None


def parse_iso8601(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def story_published_at(
    pub_date: str = "",
    published_parsed: object = None,
    updated_parsed: object = None,
) -> datetime | None:
    """Prefer feedparser parsed dates, then RSS pubDate / ISO timestamps."""
    return (
        datetime_from_struct(published_parsed)
        or datetime_from_struct(updated_parsed)
        or parse_rfc822(pub_date)
        or parse_iso8601(pub_date)
    )


def is_recent(
    published: datetime | None,
    now: datetime,
    max_age: timedelta = MAX_AGE,
) -> bool:
    """Keep undated items; drop items older than 48 hours vs the run timestamp."""
    if published is None:
        return True
    return as_utc(now) - as_utc(published) <= max_age


def stories_from_feedparser(parsed, source: str, now: datetime) -> list[dict[str, str]]:
    """Build story records from a feedparser result, dropping stale items."""
    stories = []
    for entry in getattr(parsed, "entries", []) or []:
        pub_date = str(entry.get("published") or entry.get("updated") or "")
        published = story_published_at(
            pub_date,
            entry.get("published_parsed"),
            entry.get("updated_parsed"),
        )
        if not is_recent(published, now):
            continue
        link = str(entry.get("link") or "").strip()
        full_text = ""
        for block in entry.get("content") or []:
            value = block.get("value") if isinstance(block, dict) else ""
            if value:
                full_text = plain_text(str(value))
                break
        if not full_text:
            encoded = entry.get("content_encoded") or ""
            if encoded:
                full_text = plain_text(str(encoded))
        stories.append(
            {
                "headline": str(entry.get("title") or "").strip(),
                "source": source,
                "link": resolve_publisher_url(link),
                "published_at": pub_date.strip(),
                "description": plain_text(str(entry.get("summary") or entry.get("description") or "")),
                "full_text": full_text,
            }
        )
    return stories


def stories_from_rss_tree(rss: ET.Element, source: str, now: datetime) -> list[dict[str, str]]:
    """Build story records from an ElementTree RSS document."""
    stories = []
    for item in rss.findall("./channel/item"):
        pub_date = item.findtext("pubDate", default="").strip()
        if not pub_date:
            pub_date = (item.findtext("updated") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip()
        published = story_published_at(pub_date)
        if not is_recent(published, now):
            continue
        link = item.findtext("link", default="").strip()
        stories.append(
            {
                "headline": item.findtext("title", default="").strip(),
                "source": source,
                "link": resolve_publisher_url(link),
                "published_at": pub_date,
                "description": item_description(item),
                "full_text": item_full_text(item),
            }
        )
    return stories


def fetch_feed(feed: dict[str, str], now: datetime | None = None) -> list[dict[str, str]]:
    """Download one RSS feed and return recent stories in our shared format."""
    run_at = as_utc(now) if now is not None else datetime.now(timezone.utc)
    request = Request(feed["url"], headers={"User-Agent": USER_AGENT})

    with urlopen(request, timeout=20) as response:
        raw = response.read()

    if feedparser_module is not None:
        parsed = feedparser_module.parse(raw)
        if getattr(parsed, "entries", None):
            return stories_from_feedparser(parsed, feed["source"], run_at)

    rss = ET.fromstring(raw)
    return stories_from_rss_tree(rss, feed["source"], run_at)


def collect_stories(now: datetime | None = None) -> tuple[list[dict[str, str]], list[str]]:
    """Collect all available feeds without letting one failed feed stop the run."""
    run_at = as_utc(now) if now is not None else datetime.now(timezone.utc)
    stories = []
    failed_sources = []

    for feed in SOURCES:
        try:
            stories.extend(fetch_feed(feed, now=run_at))
        except Exception:
            failed_sources.append(feed["source"])

    return stories, failed_sources


def save_run(stories: list[dict[str, str]], failed_sources: list[str]) -> Path:
    """Save the raw source evidence and quiet run record as JSON."""
    RAW_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = RAW_DATA_DIRECTORY / f"{datetime.now().date().isoformat()}.json"
    output = {"stories": stories, "failed_sources": failed_sources}
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    stories, failed_sources = collect_stories()
    saved_file = save_run(stories, failed_sources)
    print(f"Loop: collected {len(stories)} stories from the last 48 hours.")
    print(f"Saved raw data to {saved_file}")
