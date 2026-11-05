"""Load Loop settings from ``config/config.yaml``.

Missing files fall back to the same defaults the pipeline used before
the config layer existed, so mocked unit tests still run offline.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = "config/config.yaml"

# Overlay dicts for these keys replace the defaults instead of merging, so a
# shorter YAML taxonomy or feed list cannot keep leftover default labels.
REPLACE_KEYS = frozenset({"feeds", "taxonomy", "tag_weights"})

DEFAULT_CONFIG: dict[str, Any] = {
    "pipeline": {
        "recency_cutoff_hours": 48,
        "top_selected_stories": 5,
        "max_items_per_feed": 15,
        "db_retention_days": 365,
        "output_dir": "briefs",
        "db_path": "data/loop.db",
    },
    "feeds": {
        "Politico": {
            "Elections & Campaigns": (
                "https://news.google.com/rss/search?q=site:politico.com+"
                "(elections+OR+campaign+OR+primary+OR+debate+OR+candidates)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "Congress & Policy": (
                "https://news.google.com/rss/search?q=site:politico.com+"
                "(Congress+OR+Senate+OR+House+OR+bill+OR+law+OR+White+House)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
        },
        "AP News": {
            "Politics": (
                "https://news.google.com/rss/search?q=site:apnews.com+"
                "(politics+OR+election+OR+Senate+OR+House+OR+supreme+court)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
        },
        "Washington Post": {
            "Politics": (
                "https://news.google.com/rss/search?q=site:washingtonpost.com+"
                "(politics+OR+election+OR+legislation+OR+policy)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
        },
        "CBS News": {
            "Politics": "https://www.cbsnews.com/latest/rss/main",
        },
        "WSJ, Bloomberg & FT": {
            "Markets": (
                "https://news.google.com/rss/search?q=(site:wsj.com+OR+site:bloomberg.com+"
                "OR+site:ft.com)+(earnings+OR+markets+OR+stocks+OR+Wall+Street)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "Geopolitics": (
                "https://news.google.com/rss/search?q=(site:ft.com+OR+site:wsj.com)+"
                "(geopolitics+OR+trade+OR+tariffs+OR+sanctions+OR+China)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
        },
        "Reuters": {
            "Business & Markets": (
                "https://news.google.com/rss/search?q=site:reuters.com+"
                "(business+OR+markets+OR+stocks+OR+S%26P+500)&hl=en-US&gl=US&ceid=US:en"
            ),
            "Economy & Labor": (
                "https://news.google.com/rss/search?q=site:reuters.com+"
                "(economy+OR+Fed+OR+inflation+OR+payrolls+OR+GDP+OR+unemployment)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "Geopolitics": (
                "https://news.google.com/rss/search?q=site:reuters.com+"
                "(geopolitics+OR+sanctions+OR+tariffs+OR+trade+war+OR+national+security)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "Tech & Hardware": (
                "https://news.google.com/rss/search?q=site:reuters.com+"
                "(technology+OR+chips+OR+semiconductors+OR+artificial+intelligence+OR+cloud)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "M&A & Private Equity": (
                "https://news.google.com/rss/search?q=site:reuters.com+"
                "(buyout+OR+acquisition+OR+merger+OR+funding+OR+venture+capital)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
        },
        "CNBC": {
            "Markets": (
                "https://news.google.com/rss/search?q=site:cnbc.com+"
                "(markets+OR+earnings+OR+stocks+OR+Wall+Street)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "Economy & Fed": (
                "https://news.google.com/rss/search?q=site:cnbc.com+"
                "(economy+OR+Federal+Reserve+OR+inflation+OR+interest+rates+OR+jobs)"
                "&hl=en-US&gl=US&ceid=US:en"
            ),
            "Tech & Enterprise": (
                "https://news.google.com/rss/search?q=site:cnbc.com+"
                "(technology+OR+enterprise+OR+AI+OR+software)&hl=en-US&gl=US&ceid=US:en"
            ),
        },
        "MarketWatch": {
            "Top Stories": "https://feeds.marketwatch.com/marketwatch/topstories",
        },
        "Federal Reserve": {
            "Press Releases": "https://www.federalreserve.gov/feeds/press_all.xml",
        },
        "BBC": {
            "World News": "https://feeds.bbci.co.uk/news/world/rss.xml",
        },
        "TechCrunch": {
            "General": "https://techcrunch.com/feed/",
        },
        "Axios": {
            "Feed": "https://www.axios.com/feeds/feed.rss",
        },
    },
    "models": {
        "gemini": [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-2.5-flash",
        ],
        "openai_fallback": "gpt-4o-mini",
    },
    "taxonomy": {
        "US Politics": [
            "bill",
            "law",
            "legislation",
            "congress",
            "senate",
            "election",
            "campaign",
            "policy",
            "ftc",
            "probe",
            "investigation",
        ],
        "Market Valuations": [
            "earnings",
            "stock",
            "market cap",
            "valuation",
            "shares",
        ],
        "Labor & Economy": [
            "fed",
            "inflation",
            "jobs",
            "unemployment",
            "layoffs",
            "lay-offs",
            "workforce",
        ],
        "Geopolitics & Trade": [
            "tariff",
            "sanctions",
            "trade war",
            "china",
            "export controls",
        ],
        "Tech & Innovation": [
            "ai",
            "artificial intelligence",
            "claude",
            "gemini",
            "chips",
            "saas",
            "technology",
        ],
        "Venture & M&A": [
            "acquisition",
            "merger",
            "funding",
            "venture capital",
            "valuation",
        ],
    },
    "tag_weights": {
        "US Politics": 100,
        "Market Valuations": 80,
        "Labor & Economy": 70,
        "Geopolitics & Trade": 60,
        "Tech & Innovation": 50,
        "Venture & M&A": 40,
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if key in REPLACE_KEYS:
            merged[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def resolve_config_path(config_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def project_path(relative: str | Path) -> Path:
    """Resolve a config path against the project root unless it is absolute."""
    path = Path(relative)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Return pipeline settings from YAML, or internal defaults if the file is missing.

    Uses ``yaml.safe_load`` so a config file cannot construct arbitrary Python
    objects. Callers receive a copy; mutating it does not change later loads.
    """
    path = resolve_config_path(config_path)
    if not path.is_file():
        return deepcopy(DEFAULT_CONFIG)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return deepcopy(DEFAULT_CONFIG)
    return _deep_merge(DEFAULT_CONFIG, loaded)


def iter_feeds(config: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Flatten nested ``publisher: {sub-feed: url}`` (or legacy name: url) maps."""
    settings = config if config is not None else load_config()
    feeds = settings.get("feeds") or {}
    entries: list[dict[str, str]] = []
    if not isinstance(feeds, dict):
        return entries
    for publisher, value in feeds.items():
        parent = str(publisher)
        if isinstance(value, str):
            entries.append({"publisher": parent, "sub_feed": parent, "url": value})
            continue
        if not isinstance(value, dict):
            continue
        for sub_name, url in value.items():
            if isinstance(url, str) and url.strip():
                entries.append(
                    {
                        "publisher": parent,
                        "sub_feed": str(sub_name),
                        "url": url,
                    }
                )
    return entries


def nested_feed_tree(config: dict[str, Any] | None = None) -> list[tuple[str, list[str]]]:
    """Sidebar order: ``[(publisher, [sub-feed, ...]), ...]``."""
    grouped: list[tuple[str, list[str]]] = []
    index: dict[str, list[str]] = {}
    for entry in iter_feeds(config):
        parent = entry["publisher"]
        child = entry["sub_feed"]
        if parent not in index:
            children: list[str] = []
            index[parent] = children
            grouped.append((parent, children))
        if child not in index[parent]:
            index[parent].append(child)
    return grouped


def feed_label(publisher: str, sub_feed: str) -> str:
    if not sub_feed or sub_feed == publisher:
        return publisher
    return f"{publisher} / {sub_feed}"


def flatten_feed_urls(config: dict[str, Any] | None = None) -> dict[str, str]:
    """``Publisher / Sub-feed`` labels mapped to RSS URLs."""
    return {
        feed_label(entry["publisher"], entry["sub_feed"]): entry["url"]
        for entry in iter_feeds(config)
    }
