"""Collect the latest items from V1's public RSS feeds.

Run from the project folder:
    python3 src/collect_stories.py
"""

from datetime import date
import json
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


FEEDS = [
    {
        "source": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "source": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
    },
    {
        "source": "NPR Economy",
        "url": "https://feeds.npr.org/1017/rss.xml",
    },
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIRECTORY = PROJECT_ROOT / "data" / "raw"


def fetch_feed(feed: dict[str, str]) -> list[dict[str, str]]:
    """Download one RSS feed and return its stories in our shared format."""
    request = Request(feed["url"], headers={"User-Agent": "AI-Market-Briefing/0.1"})

    with urlopen(request, timeout=20) as response:
        rss = ET.fromstring(response.read())

    stories = []
    for item in rss.findall("./channel/item"):
        stories.append(
            {
                "headline": item.findtext("title", default="").strip(),
                "source": feed["source"],
                "link": item.findtext("link", default="").strip(),
                "published_at": item.findtext("pubDate", default="").strip(),
            }
        )

    return stories


def collect_stories() -> tuple[list[dict[str, str]], list[str]]:
    """Collect all available feeds without letting one failed feed stop the run."""
    stories = []
    failed_sources = []

    for feed in FEEDS:
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
